# leanprover-contrib

This repo creates some basic checkin/CI for Lean projects that are not part of mathlib.

Current local usage:
```
python3 test_builds.py <leanprover-community-bot GitHub PAT>
```

But it's intended to run as a script in this repository.

The project is still in a design phase.

## How it works

* The maintainer of an external project adds their package info to [projects.yml](blob/master/projects/projects.yml).
  This project should have some number of `lean-3.*.*` branches.
  Any dependencies of the project must also be listed in `projects.yml`.

* Daily, we pull the current versions of all checked in projects, as well as mathlib.
  We try to build each `lean-3.*.*` branch of each project,
  with the project's dependencies updated.
  We do this with a topological sort. For example, suppose we're working with `lean-3.16.3`.
  1. Set `mathlib` to its `3.16.3` branch.
  2. For project `P1` that depends only on `mathlib`, build its `3.16.3` branch against `mathlib` from step 1.
  3. For project `P2` that depends on `mathlib` and `P1`, build its `3.16.3` branch against `mathlib` from step 1 and `P1` from step 2.

* If a project fails, we notify the project owners.
  This failure may be caused by changes in a dependency (probably mathlib) or a downstream failure.


## What to do as a project owner

This is still under development, but you can help if you have a Lean project that you want regularly tested.

You should ensure a few things:

* Your project needs to have `lean-3.*.*` branches corresponding to releases of Lean.
  If you don't have these branches, nothing will be checked: we do not check `master`.
* There are restrictions on the `leanpkg.toml` file in each `lean-3.*.*` branch:
  - The `lean_version` field must match the version in the branch name.
  - The `name` field must be the same as your project's GitHub repository.
    (E.g. [`lean-perfectoid-spaces`](https://github.com/leanprover-community/lean-perfectoid-spaces/blob/master/leanpkg.toml))
* Your project should not change dependencies between versions:
  every `leanpkg.toml` should have the same list of dependency names.
  (It's okay if the `rev` fields are different.)
* All of these dependencies should also meet these criteria and be checked into this repo.

Hopefully these restrictions will be loosened as development goes on.

If you meet these criteria, you can sign up by making a pull request to
[`projects.yml`](https://github.com/leanprover-contrib/leanprover-contrib/blob/master/projects/projects.yml).

```yaml
mathematica:
  description: 'A link between Lean and Mathematica'
  organization: 'robertylewis'
  maintainers:
    - robertylewis
    - minchaowu
  report-build-failures: false
```

Note that if you sign up now, you may get some spam in the form of GitHub issues and notifications.
This is the price of being an early adopter.

Including the optional `report-build-failures: false` line will prevent the tool
from opening issues in your repository.
If you don't have any complicated dependencies (e.g. your project only depends on mathlib),
and you're using the Lean upgrade action script,
you likely want to set this to `false`.

## Other Lean action scripts

We strongly recommend installing two GitHub Actions in your project repository.

* [lean-upgrade-action](https://github.com/leanprover-contrib/lean-upgrade-action)
  will run `leanproject upgrade` daily, and push the result to your repository if it succeeds.
  This is quite similar to what the `leanprover-contrib` tool does,
  except it does not handle transitive or diamond dependencies very well
  (e.g. your repo depends on project A which depends on mathlib).
* [update-versions-action](https://github.com/leanprover-contrib/update-versions-action)
  will mirror commits to your `master` branch to the appropriate `lean-x.y.z` branch.
  The `leanprover-contrib` tool depends on these version branches existing,
  so if you do not use this action, you will have to maintain them manually.

## TODO

* Use `mathlibtools` as a Python project instead of `leanproject` CLI?
* We can list checked in projects on the community website. (Sorted by # of GH stars as popularity maybe?)