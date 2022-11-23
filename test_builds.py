from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Set, Mapping, Optional, Tuple, Dict
from toposort import toposort_flatten
import yaml
import git
import toml
import subprocess
import github_reports
import re
import sys
import argparse
import json

@dataclass
class Project:
    name: str
    branches: List[Tuple[int]]
    repo: git.Repo
    dependencies: Set[str]
    organization: str
    owners: List[str]
    report_failure: bool
    display: bool

@dataclass
class Failure:
    project: str
    version: Tuple[int]
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

    def report_issue(self, project_statuses, mathlib_prev = None):
        if self.is_new and projects[self.project].report_failure:
            ppversion = '.'.join(str(s) for s in self.version)
            project = projects[self.project]
            branch_url = f'https://github.com/{project.organization}/{self.project}/tree/lean-{ppversion}'
            mathlib_curr = project_statuses['mathlib']['latest_test'] if 'mathlib' in project_statuses else None
            # if mathlib_prev is not None and mathlib_prev != :
            git_diff_url = f'https://github.com/leanprover-community/mathlib/compare/{mathlib_prev}...{mathlib_curr}' \
                if mathlib_prev is not None and mathlib_curr is not None and mathlib_prev != mathlib_curr \
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
            project_statuses[self.project]['issue'] = issue

def format_project_link(project_name):
    org = projects[project_name].organization
    return f'[{project_name}](https://github.com/{org}/{project_name})'

class DependencyFailure(Failure):
    def __init__(self, project, version, is_new, dependencies):
        self.dependencies = dependencies
        super().__init__(project, version, is_new)

    def __repr__(self):
        return f'{self.project} was not built on version {self.version} because some of its dependencies do not have a corresponding version: {self.dependencies}'

    def report_issue(self, project_statuses, mathlib_prev = None):
        if self.is_new and projects[self.project].report_failure:
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
            project_statuses[self.project]['issue'] = issue


root = Path('.').absolute()
project_root = root / 'projects'

git_prefix = 'https://github.com/'

projects = {}
mathlib_repo: git.Repo = None

def get_project_repo(project_name):
    if project_name == 'mathlib':
        return mathlib_repo
    else:
        return projects[project_name].repo

def lean_version_from_remote_ref(ref):
    """ Note that ref should be the head name without the leading `origin/` """
    m = re.fullmatch('lean-(\d+).(\d+).(\d+)', ref)
    if not m:
        return None
    return tuple(int(i) for i in m.groups())

def remote_ref_from_lean_version(version):
    return 'lean-{0}.{1}.{2}'.format(*version)

# returns a dict loaded from yaml
def load_version_history():
    with open(root / 'version_history.yml', 'r') as yaml_file:
        dic = yaml.safe_load(yaml_file.read())
        return {} if dic is None else dic


def write_version_history_js(hist):
    def vers_id(lv):
        return str(hash(lv) % 100000)
    def strip_prefix(lv):
        return tuple(int(i) for i in lv.split('.'))
    def not_only_mathlib(lv):
        lvr = lean_version_from_remote_ref(lv)
        print(lvr)
        return any(p for p in projects if p != 'mathlib' and projects[p].display and lvr in projects[p].branches)
    hist2 = [lv for lv in hist if not_only_mathlib(lv)]
    print(hist2)
    project_out = []
    for project in [project for project in projects if projects[project].display]:
        entry = {'name': project}
        for lean_version in hist2:
            if project in hist[lean_version]:
                entry[vers_id(lean_version)] = '✓' if hist[lean_version][project]['success'] else '×'
            else:
                entry[vers_id(lean_version)] = ''
        project_out.append(entry)
    version_out = []
    for lean_version in hist2:
        version_out.append({'title': lean_version[5:], 'field': vers_id(lean_version), 'minWidth':75})
    version_out.sort(key=lambda dic: strip_prefix(dic['title']), reverse=True)
    version_out = [{'title': 'Project', 'field': 'name', 'minWidth':140}] + version_out
    with open(root / 'projects.js', 'w') as js_file:
        js_file.write('project_cols = ' + str(version_out))
        js_file.write('\nprojects = ' + str(project_out))

def populate_projects():
    global mathlib_repo
    print('cloning mathlib')
    mathlib_repo = git.Repo.clone_from(f'{git_prefix}leanprover-community/mathlib', project_root / 'mathlib', no_checkout=True)

    with open(root/'projects'/'projects.yml', 'r') as project_file:
        projects_data = yaml.safe_load(project_file.read())

    print(f'found {len(projects_data)} projects:')
    for p in projects_data:
        print(p)

    print()
    for project_name in projects_data:
        project_org = projects_data[project_name]['organization']
        repo = git.Repo.clone_from(f'{git_prefix}{project_org}/{project_name}', project_root / project_name, no_checkout=True)
        repo.git.checkout(['HEAD', '--', 'leanpkg.toml'])
        versions = [vs for vs in [lean_version_from_remote_ref(ref.remote_head) for ref in repo.remotes[0].refs] if vs is not None]
        print(f'{project_name} has {len(versions)} version branches:')
        print(versions)

        with open(project_root / project_name / 'leanpkg.toml', 'r') as lean_toml:
            parsed_toml = toml.loads(lean_toml.read())
        deps = set(d for d in parsed_toml['dependencies'])
        owners = projects_data[project_name]['maintainers']
        report_failure = 'report-build-failures' not in projects_data[project_name] or projects_data[project_name]['report-build-failures']
        display = 'display' not in projects_data[project_name] or projects_data[project_name]['display']
        projects[project_name] = Project(project_name, versions, repo, deps, project_org, owners, report_failure, display)
        print(f'{project_name} has dependencies: {deps}')

    mathlib_versions = [vs for vs in [lean_version_from_remote_ref(ref.remote_head) for ref in mathlib_repo.remotes[0].refs] if vs is not None]
    projects['mathlib'] = Project('mathlib', mathlib_versions, mathlib_repo, set(), 'leanprover-community', ['leanprover-community-bot'], False, True)


def checkout_version(repo, version):
    repo.remotes[0].refs.__getattr__(remote_ref_from_lean_version(version)).checkout()

def update_mathlib_to_version(version):
    print(f'updating mathlib to version {version}')
    checkout_version(mathlib_repo, version)
    subprocess.run(['leanproject', 'get-mathlib-cache'], cwd = project_root / 'mathlib')

def leanpkg_add_local_dependency(project_name, dependency):
    subprocess.run(['leanpkg', 'add', project_root / dependency], cwd= project_root / project_name)

def fail_with_early_stop(p):
    error = re.compile('[^:\n]*:\d*:\d*:\serror')
    while True:
        output = p.stdout.readline()
        if (output == b'' or output is None) and p.poll() is not None:
            return False
        if output is not None and error.match(output.decode('utf-8')):
            p.kill()
            return True

def leanpkg_build(project_name):
    p = subprocess.Popen(['leanpkg', 'build'], cwd = project_root / project_name, stdout = subprocess.PIPE)
    failure = fail_with_early_stop(p)
    return not failure

def get_git_sha(version, project_name):
    key = remote_ref_from_lean_version(version)
    return get_project_repo(project_name).remotes[0].refs.__getattr__(key).object.hexsha

def add_success_to_project_statuses(version, project_name, project_statuses):
    sha = get_git_sha(version, project_name)
    if project_name in project_statuses and 'issue' in project_statuses[project_name]:
        github_reports.resolve_issue(f'{projects[project_name].organization}/{project_name}', project_statuses[project_name]['issue'])
        del project_statuses[project_name]['issue']
    project_statuses[project_name] = {'latest_success':sha, 'latest_test':sha, 'success':True}

def add_failure_to_project_statuses(version, project_name, project_statuses):
    sha = get_git_sha(version, project_name)
    if project_name in project_statuses:
        project_statuses[project_name]['latest_test'] = sha
        project_statuses[project_name]['success'] = False
    else:
        project_statuses[project_name] = {'latest_test':sha, 'success':False}

def failing_test(version, project_name, project_statuses, failures, new_failure):
    failures[project_name] = new_failure
    add_failure_to_project_statuses(version, project_name, project_statuses)

def previous_run_exists_and_failed(version, project_name, project_statuses):
    return project_name in project_statuses \
      and not project_statuses[project_name]['success']


def test_project_on_version(version, project_name, failures, project_statuses):
    print(f'testing {project_name} on version {version}')
    project = projects[project_name]

    failure = next((failures[dep] for dep in project.dependencies if dep in failures), None)
    if failure is not None:
        is_new = not previous_run_exists_and_failed(version, project_name, project_statuses)
        failing_test(version, project_name, project_statuses, failures, BuildFailure(project_name, version, is_new, failure))
        return
    repo = project.repo
    repo.head.reset(index=True, working_tree=True)
    checkout_version(repo, version)
    # we are now operating on a detached head 'origin/lean-*.*.*' branch

    for dep in project.dependencies:
        leanpkg_add_local_dependency(project_name, dep)

    if leanpkg_build(project_name):
        add_success_to_project_statuses(version, project_name, project_statuses)
    else:
        is_new = not previous_run_exists_and_failed(version, project_name, project_statuses)
        failing_test(version, project_name, project_statuses, failures, BuildFailure(project_name, version, is_new, None))

def project_has_changes_on_version(version, project_name, project_statuses):
    if project_name not in project_statuses:
        return True
    latest_test = project_statuses[project_name]['latest_test']
    curr_sha = get_git_sha(version, project_name)
    return latest_test != curr_sha

def changes_on_version(version, project_names, project_statuses):
    return any(project_has_changes_on_version(version, project_name, project_statuses) for project_name in project_names)

def test_on_lean_version(version, project_statuses):
    print(f'\nRunning tests on Lean version {version}')
    mathlib_prev = project_statuses['mathlib']['latest_test'] \
        if 'mathlib' in project_statuses else None
    version_projects = [p for p in projects if version in projects[p].branches]
    print(f'version projects: {version_projects}')

    if not changes_on_version(version, version_projects, project_statuses):
        print(f'no projects have changed on version {version} since the last run.\n')
        return

    if version in projects['mathlib'].branches:
        add_success_to_project_statuses(version, 'mathlib', project_statuses)

    ordered_projects = toposort_flatten({p:projects[p].dependencies for p in version_projects})
    # if 'mathlib' in ordered_projects:
    #     ordered_projects.remove('mathlib')

    failures = {}
    i = 0
    while i < len(ordered_projects):
        p = ordered_projects[i]
        missing_deps = [dep for dep in projects[p].dependencies if dep not in ordered_projects]
        if p not in version_projects or len(missing_deps) > 0:
            print(f'removing {p}')
            del ordered_projects[i]
            if p in version_projects:
                is_new = not previous_run_exists_and_failed(version, p, project_statuses)
                failing_test(version, p, project_statuses, failures, DependencyFailure(p, version, is_new, missing_deps))
        else:
            i += 1

    if len(ordered_projects) > 0 and any(project != 'mathlib' for project in ordered_projects):
        print(f'\nbuilding projects in order: {ordered_projects}')
        if 'mathlib' in ordered_projects:
            update_mathlib_to_version(version)
        for project_name in [project_name for project_name in ordered_projects if project_name != 'mathlib']:
            test_project_on_version(version, project_name, failures, project_statuses)

    if len(failures) > 0:
        print(f'\n{len(failures)} failures:')
    for f in failures:
        print(failures[f])
        failures[f].report_issue(project_statuses, mathlib_prev)

def collect_versions(version_history) -> Dict[Tuple[int], List[Project]]:
    versions = {}
    for name, project in projects.items():
        for version in project.branches:
            key = remote_ref_from_lean_version(version)
            if key not in version_history or project_has_changes_on_version(version, name, version_history[key]):
                versions.setdefault(version, []).append(project)
    return versions

def arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--github_token', default=None)
    subparsers = parser.add_subparsers(title='subcommands',
                                   description='valid subcommands',
                                   dest='subparser')
    subparsers.add_parser('write_js', help="Generate the js file from the yaml")
    concat_parser = subparsers.add_parser('concat_outputs',
        help="concatenate yaml files generated by the --version flag")
    concat_parser.add_argument('files', nargs='*')

    load_parser = subparsers.add_parser('load_versions',
        help="generate a json file listing all available versions")
    load_parser.add_argument('json_output')
    parser.add_argument('--version', default=None,
        help="Check third party packages for only a single version")
    return parser


if __name__ == "__main__":
    args = arg_parser().parse_args()
    if args.github_token:
        github_reports.setup(args.github_token)
    else:
        github_reports.setup()

    version_history = load_version_history()

    if args.subparser == 'concat_outputs':
        for f in args.files:
            with open(f, 'r') as yaml_file:
                data = yaml.safe_load(yaml_file.read())
            for ver, ver_data in data.items():
                for proj, proj_data in ver_data.items():
                    version_history.setdefault(ver, {}).setdefault(proj, {}).update(proj_data)
        with open(root / 'version_history.yml', 'w') as yaml_file:
            yaml.dump(version_history, yaml_file)
        raise SystemExit()

    populate_projects()

    if args.subparser == 'write_js':
        write_version_history_js(version_history)
        raise SystemExit()

    if args.subparser == 'load_versions':
        # stdout is impractical because all our subprocesses write to it too
        with open(args.json_output, 'w') as f:
            json.dump([
                remote_ref_from_lean_version(v) for v in collect_versions(version_history)], f)
        raise SystemExit()

    if args.version:
        key = args.version
        version = lean_version_from_remote_ref(args.version)
        project_statuses = version_history.setdefault(key, {})
        test_on_lean_version(version, project_statuses)
        with open(root / f'version_history.yml', 'w') as yaml_file:
            yaml.dump({key: project_statuses}, yaml_file)
        raise SystemExit()

    for version in collect_versions(version_history):
        key = remote_ref_from_lean_version(version)
        project_statuses = version_history.setdefault(key, {})
        test_on_lean_version(version, project_statuses)

    with open(root / 'version_history.yml', 'w') as yaml_file:
        yaml.dump(version_history, yaml_file)
    write_version_history_js(version_history)
