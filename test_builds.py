from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Set, Mapping, Optional
from toposort import toposort_flatten
import yaml
import git 
import toml
import subprocess

@dataclass
class Project:
    name: str
    branches: List[List[int]]
    repo: git.Repo
    dependencies: Set[str]

class BuildFailure:
    def __init__(self, project, version, traceback=None):
        self.project = project 
        self.version = version 
        self.traceback = traceback

    def find_trans_fail(self):
        return self if self.traceback is None else self.traceback.find_trans_fail()

    def __repr__(self):
        s = f'{self.project} failed to build on version {self.version}.'
        if self.traceback is not None:
            s += f'\n  This may be because of a transitive failure in {self.find_trans_fail().project}'
        return s


root = Path('.').absolute()

contrib_org = 'git@github.com:leanprover-contrib/'

projects = {}

print('cloning mathlib')
mathlib_repo = git.Repo.clone_from('git@github.com:leanprover-community/mathlib', root / 'mathlib')
    

def lean_version_from_remote_ref(ref):
    if not ref.startswith('origin/lean-'):
        return None
    return [int(i) for i in ref[12:].split('.')]

def remote_ref_from_lean_version(version):
    return 'lean-{0}.{1}.{2}'.format(*version)

def populate_projects():
    with open(root/'projects'/'projects.yml', 'r') as project_file:
        projects_data = yaml.safe_load(project_file.read())

    print(f'found {len(projects_data)} projects:')
    for p in projects_data:
        print(p)

    print()
    for project_name in projects_data:
        repo = git.Repo.clone_from(contrib_org + project_name, root / project_name)
        versions = [vs for vs in [lean_version_from_remote_ref(ref.name) for ref in repo.remotes[0].refs] if vs is not None]
        print(f'{project_name} has {len(versions)} version branches:')
        print(versions)

        with open(root / project_name / 'leanpkg.toml', 'r') as lean_toml:
            parsed_toml = toml.loads(lean_toml.read())
        deps = set(d for d in parsed_toml['dependencies'])
        projects[project_name] = Project(project_name, versions, repo, deps)
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

def test_project_on_version(project_name, version, failures):
    print(f'testing {project_name} on version {version}')
    project = projects[project_name]

    failure = next((failures[dep] for dep in project.dependencies if dep in failures), None)
    if failure is not None:
        failures[project_name] = BuildFailure(project_name, version, failure)
        return
    repo = project.repo
    checkout_version(repo, version)
    # we are now operating on a detached head 'origin/lean-*.*.*' branch

    for dep in project.dependencies:
        leanpkg_add_local_dependency(project_name, dep)

    if not leanpkg_build(project_name):
        failures[project_name] = BuildFailure(project_name, version, None)


def test_on_lean_version(version):
    version_projects = [p for p in projects if version in projects[p].branches]
    ordered_projects = toposort_flatten({p:projects[p].dependencies for p in version_projects})
    print(f'building projects in order: {ordered_projects}')
    ordered_projects.remove('mathlib')
    update_mathlib_to_version(version)
    failures = {}
    for project_name in ordered_projects:
        test_project_on_version(project_name, version, failures)

    if len(failures) > 0:
        print('Failures:')
    for f in failures:
        print(failures[f])

populate_projects()

test_on_lean_version([3,16,3])

# print(toposort_flatten({p : projects[p].dependencies for p in projects}))

# print(projects)