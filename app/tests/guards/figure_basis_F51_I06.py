"""F51-I06's pending figure-basis hits (`app/tests/test_figure_basis.py`): the bare `roas` keys of
`/api/meta/brands/{b}/spend` and the dashboard month, renamed by F51-I06 (`roas_platform`,
`roas_all_channels`). F51-I06 deletes this module, never the gate. Lower a count when its hit
goes; never raise one or add an entry."""

PENDING = {
    ("app/dashboard/repository.py", "roas"): 1,  # month payload key -> roas_all_channels
    ("app/meta/routes.py", "roas"): 5,  # /spend rows, model field and total -> roas_platform
}
