# ONMI-STAY Harness Finding

## Finding

ONMI-STAY is a TypeScript + Jest auth/API project.

Detected project profile:

- language: TypeScript
- test framework: Jest
- domains: auth, tests, api

## Incorrect Previous Install

`auth-bug-core@0.1.0` was installed, but it is Python + pytest only.

That made the initial flow too pinpointed around the Python auth preset instead of the project-specific harness spine.

## Correct Harness

`typescript-jest-auth-core`

This preset is for TypeScript + Jest auth/API bug work.

## Required Product Fix

- compatibility gate
- TypeScript/Jest harness preset
- Jest validation lane
- warning for incompatible active harness

## Source Safety Note

Cambrian did not auto-apply a patch.

`authMiddleware.ts` contains changes, but the project root is not a git repo, so authorship cannot be verified by git diff.
