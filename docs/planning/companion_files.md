# Companion-file checks (not implemented yet)

Design notes carried over from the stub checks `check_aux_uncertainty_id`,
`check_conventions` and `check_external_variables`, which were removed because they did
nothing. compliance-checker does not pass companion files to `check_*` methods, so the
mechanism for getting them to a check still has to be designed (see `companion_file.py`).

## aux_uncertainty_id

- Space-delimited string of uncertainty modifiers (each must come from the CVs).
  - Build the list of uncertainty variable ids `{variable_id}{modifier}`.
- If the uncertainty variables exist in the dataset and no companion files were provided,
  ask for one companion file per uncertainty variable id.
- If they do not exist and companion files were provided:
  - with several ids, expect the same number of companion files
  - check that the `variable_id` in each companion file is one of the uncertainty ids
- Finally check that `{variable_id}` has
  `ancillary_variables = "{variable_id}{modifier} {variable_id}{modifier2} ..."`.

## Conventions

- At least `ODS-<version>` must be present (membership in the CVs is already checked).
- If a `CF-` convention is listed:
  - only one CF convention may be listed
  - map it to a compliance-checker `-t` option; if there is none, report an error
  - if there is one, check that the user actually ran with that `-t` option, and if not
    tell them to re-run with it

## external_variables

- If present, warn against using it and recommend bounds on time, latitude, longitude and
  depth instead, e.g.:

  ```
  double time(time) ;
          time:axis = "T" ;
          time:standard_name = "time" ;
          time:long_name = "time" ;
          time:bounds = "time_bnds" ;
          time:units = "days since 2003-01-01" ;
          time:calendar = "standard" ;
  double time_bnds(time, bnds) ;
  ```
- Extract the list of external variables from the space-separated string.
  - They must not be variables in the dataset; they come from companion files.
  - Check that each name exists in the companion files.
