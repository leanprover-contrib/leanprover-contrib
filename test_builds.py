from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Set, Mapping, Optional
from toposort import toposort_flatten
import yaml
import git
import toml
import subprocess
import github_reports

@dataclass
class Project:
    name: str
    branches: List[List[int]]
    repo: git.Repo
    dependencies: Set[str]
    organization: str
    owners: List[str]

@dataclass
class Failure:
    project: str
    version: List[int]
    is_new: bool

class BuildFailure(Failure):
    def __init__(self, project, version, is_new, traceback=None):
        self.traceback = traceback
        super().__init__(project, version, is_new)

    def find_trans_fail(self):
        return self if self.traceback is None else self.traceback.find_trans_fail()

    def __repr__(self):
        s = f'{self.project} failed to build on version {self.version}.'
        if self.traceback is not None:
            s += f'\n  This may be because of a transitive failure in {self.find_trans_fail().project}'
        return s

    def report_issue(self, version_history, mathlib_prev = None):
        if self.is_new:
            version_key = remote_ref_from_lean_version(self.version)
            ppversion = '.'.join(str(s) for s in self.version)
            project = projects[self.project]
            branch_url = f'https://github.com/{project.organization}/{self.project}/tree/lean-{ppversion}'
            mathlib_curr = version_history[version_key]['mathlib']['latest_test']
            # if mathlib_prev is not None and mathlib_prev != :
            git_diff_url = f'https://github.com/leanprover-community/mathlib/compare/{mathlib_prev}...{mathlib_curr}' \
                if mathlib_prev is not None and mathlib_prev != mathlib_curr \
                else None

            s = \
f"""This is an automated message from the [leanprover-contrib](https://github.com/leanprover-contrib/leanprover-contrib) repository.

Your project's [lean-{ppversion}]({branch_url}) branch has failed to build with recent updates to mathlib and/or its other dependencies."""

            if git_diff_url is not None:
                s += f'\n\nThis is often due to changes in mathlib, but could also happen due to changes in other dependencies or your own changes to your branch. '
                s += f'If it is due to mathlib, the conflicting changes occur in [this range]({git_diff_url}).'

            s += f'\n\nThe failure occurred using Lean version {ppversion}.'
            if self.traceback is not None:
                s += f'\n\nThis failure may have been caused by a failure in the {self.find_trans_fail().project} on which your project depends.'
            issue = github_reports.open_issue_on_failure(
                f'{project.organization}/{self.project}',
                f'Build failure on automatic dependency update on `lean-{ppversion}`',
                s,
                project.owners)
            version_history[version_key][self.project]['issue'] = issue

def format_project_link(project_name):
    org = projects[project_name].organization
    return f'[{project_name}](https://github.com/{org}/{project_name})'

class DependencyFailure(Failure):
    def __init__(self, project, version, is_new, dependencies):
        self.dependencies = dependencies
        super().__init__(project, version, is_new)

    def __repr__(self):
        return f'{self.project} was not built on version {self.version} because some of its dependencies do not have a corresponding version: {self.dependencies}'

    def report_issue(self, version_history, mathlib_prev = None):
        if self.is_new:
            ppversion = '.'.join(str(s) for s in self.version)
            deplist = '\n'.join('* {format_project_link(d)}' for d in self.dependencies)
            s = \
f"""This is an automated message from the [leanprover-contrib](https://github.com/leanprover-contrib/leanprover-contrib) repository.

Your project has a `lean-{ppversion}` branch, but some of its dependencies do not:
{deplist}"""
            project = projects[self.project]
            issue = github_reports.open_issue_on_failure(
                f'{project.organization}/{self.project}',
                f'Dependency error on `lean-{ppversion}`',
                s,
                project.owners)
            version_history[remote_ref_from_lean_version(self.version)][self.project]['issue'] = issue


root = Path('.').absolute()

git_prefix = 'git@github.com'

projects = {}

print('cloning mathlib')
mathlib_repo = git.Repo.clone_from('git@github.com:leanprover-community/mathlib', root / 'mathlib')

def get_project_repo(project_name):
    if project_name == 'mathlib':
        return mathlib_repo
    else:
        return projects[project_name].repo

def lean_version_from_remote_ref(ref):
    if not ref.startswith('origin/lean-'):
        return None
    return [int(i) for i in ref[12:].split('.')]

def remote_ref_from_lean_version(version):
    return 'lean-{0}.{1}.{2}'.format(*version)

# returns a dict loaded from yaml
def load_version_history():
    with open(root / 'version_history.yml', 'r') as yaml_file:
        dic = yaml.safe_load(yaml_file.read())
        return {} if dic is None else dic


def write_version_history(hist):
    with open(root / 'version_history.yml', 'w') as yaml_file:
        yaml.dump(hist, yaml_file)

def populate_projects():
    with open(root/'projects'/'projects.yml', 'r') as project_file:
        projects_data = yaml.safe_load(project_file.read())

    print(f'found {len(projects_data)} projects:')
    for p in projects_data:
        print(p)

    print()
    for project_name in projects_data:
        project_org = projects_data[project_name]['organization']
        repo = git.Repo.clone_from(f'{git_prefix}:{project_org}/{project_name}', root / project_name)
        versions = [vs for vs in [lean_version_from_remote_ref(ref.name) for ref in repo.remotes[0].refs] if vs is not None]
        print(f'{project_name} has {len(versions)} version branches:')
        print(versions)

        with open(root / project_name / 'leanpkg.toml', 'r') as lean_toml:
            parsed_toml = toml.loads(lean_toml.read())
        deps = set(d for d in parsed_toml['dependencies'])
        owners = projects_data[project_name]['maintainers']
        projects[project_name] = Project(project_name, versions, repo, deps, project_org, owners)
        print(f'{project_name} has dependencies: {deps}')


def checkout_version(repo, version):
    repo.remotes[0].refs.__getattr__(remote_ref_from_lean_version(version)).checkout()

def update_mathlib_to_version(version):
    print(f'updating mathlib to version {version}')
    checkout_version(mathlib_repo, version)
    subprocess.run(['leanproject', 'get-mathlib-cache'], cwd = root / 'mathlib')

def leanpkg_add_local_dependency(project_name, dependency):
    subprocess.run(['leanpkg', 'add', root / dependency], cwd= root / project_name)

def leanpkg_build(project_name):
    p = subprocess.Popen(['leanpkg', 'build'], cwd = root / project_name)
    p.communicate()
    return p.returncode == 0

def get_git_sha(version, project_name):
    key = remote_ref_from_lean_version(version)
    return get_project_repo(project_name).remotes[0].refs.__getattr__(key).object.hexsha

def add_success_to_version_history(version, project_name, version_history):
    key = remote_ref_from_lean_version(version)
    sha = get_git_sha(version, project_name)
    if key not in version_history:
        version_history[key] = {project_name:{'latest_success':sha, 'latest_test':sha, 'success':True}}
    else:
        if project_name in version_history[key] and 'issue' in version_history[key][project_name]:
            github_reports.resolve_issue(f'{projects[project_name].organization}/{project_name}', version_history[key][project_name]['issue'])
        version_history[key][project_name] = {'latest_success':sha, 'latest_test':sha, 'success':True}

def add_failure_to_version_history(version, project_name, version_history):
    key = remote_ref_from_lean_version(version)
    sha = get_git_sha(version, project_name)
    if key not in version_history:
        version_history[key] = {project_name:{'latest_test':sha, 'success':False}}
    elif project_name in version_history[key]:
        version_history[key][project_name]['latest_test'] = sha
        version_history[key][project_name]['success'] = False
    else:
        version_history[key][project_name] = {'latest_test':sha, 'success':False}

def failing_test(version, project_name, version_history, failures, new_failure):
    failures[project_name] = new_failure
    add_failure_to_version_history(version, project_name, version_history)

def previous_run_exists_and_failed(version, project_name, version_history):
    key = remote_ref_from_lean_version(version)
    return key in version_history \
      and project_name in version_history[key] \
      and not version_history[key][project_name]['success']


def test_project_on_version(version, project_name, failures, version_history):
    print(f'testing {project_name} on version {version}')
    project = projects[project_name]

    failure = next((failures[dep] for dep in project.dependencies if dep in failures), None)
    if failure is not None:
        is_new = not previous_run_exists_and_failed(version, project_name, version_history)
        failing_test(version, project_name, version_history, failures, BuildFailure(project_name, version, is_new, failure))
        return
    repo = project.repo
    repo.head.reset(index=True, working_tree=True)
    checkout_version(repo, version)
    # we are now operating on a detached head 'origin/lean-*.*.*' branch

    for dep in project.dependencies:
        leanpkg_add_local_dependency(project_name, dep)

    if leanpkg_build(project_name):
        add_success_to_version_history(version, project_name, version_history)
    else:
        is_new = not previous_run_exists_and_failed(version, project_name, version_history)
        failing_test(version, project_name, version_history, failures, BuildFailure(project_name, version, is_new, None))

def project_has_changes_on_version(version, project_name, version_history):
    key = remote_ref_from_lean_version(version)
    if key not in version_history or project_name not in version_history[key]:
        return True
    latest_test = version_history[key][project_name]['latest_test']
    curr_sha = get_git_sha(version, project_name)
    return latest_test != curr_sha

def changes_on_version(version, project_names, version_history):
    return any(project_has_changes_on_version(version, project_name, version_history) for project_name in project_names)

def test_on_lean_version(version, version_history):
    print(f'\nRunning tests on Lean version {version}')
    key = remote_ref_from_lean_version(version)
    mathlib_prev = version_history[key]['mathlib']['latest_test'] if 'mathlib' in version_history[key] else None
    add_success_to_version_history(version, 'mathlib', version_history)
    version_projects = [p for p in projects if version in projects[p].branches]
    print(f'version projects: {version_projects}')

    if not changes_on_version(version, ['mathlib'] + version_projects, version_history):
        print(f'no projects have changed on version {version} since the last run.\n')
        return

    ordered_projects = toposort_flatten({p:projects[p].dependencies for p in version_projects})
    if 'mathlib' in ordered_projects:
        ordered_projects.remove('mathlib')

    failures = {}
    i = 0
    while i < len(ordered_projects):
        p = ordered_projects[i]
        missing_deps = [dep for dep in projects[p].dependencies if dep not in ordered_projects and dep != 'mathlib']
        if p not in version_projects or len(missing_deps) > 0:
            print(f'removing {p}')
            del ordered_projects[i]
            if p in version_projects:
                is_new = not previous_run_exists_and_failed(version, p, version_history)
                failing_test(version, p, version_history, failures, DependencyFailure(p, version, is_new, missing_deps))
        else:
            i += 1

    if len(ordered_projects) > 0:
        print(f'\nbuilding projects in order: {ordered_projects}')
        update_mathlib_to_version(version)
        for project_name in ordered_projects:
            test_project_on_version(version, project_name, failures, version_history)

    if len(failures) > 0:
        print(f'\n{len(failures)} failures:')
    for f in failures:
        print(failures[f])
        failures[f].report_issue(version_history, mathlib_prev)

populate_projects()

version_history = load_version_history()

test_on_lean_version([3,16,3], version_history)
test_on_lean_version([3,17,0], version_history)
test_on_lean_version([3,17,1], version_history)

write_version_history(version_history)

# print(toposort_flatten({p : projects[p].dependencies for p in projects}))

# print(projects)