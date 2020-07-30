# leanprover-contrib

This repo creates some basic checkin/CI for Lean projects that are not part of mathlib.

It is still in a design phase. What I envision is this:

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

* We also want to notice when new Lean versions are released,
  check if projects can be updated without changes,
  and suggest to project owners that they create a new `lean-3.*.*` branch.


## TODO

* The logic to test new Lean versions isn't there yet.
* Put things into CI, including failure/upgrade notifications (as issues or PRs to the project repo?)
* Right now projects are assumed to be forked to the `leanprover-contrib` org, change this.
* Use `mathlibtools` as a Python project instead of `leanproject` CLI?
* We can list checked in projects on the community website. (Sorted by # of GH stars as popularity maybe?)