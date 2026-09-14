"""
Custom dataclass object for cc-plugin-obs4mips that is more robust than just using the
compliance-checker ``@check_has()`` decorator. AttrSpec is a base dataclass that stores
the specifications that are then used in ``cc_plugin_obs4mips/checks/`` to validate
NetCDFs against the specifications.
"""

from dataclasses import dataclass, replace
from typing import Callable, Iterable, Mapping, Optional

from compliance_checker.base import BaseCheck

# ODS requirement names mapped to Compliance Checker's supported severity levels.
REQUIRED = BaseCheck.HIGH
RECOMMENDED = BaseCheck.MEDIUM
OPTIONAL = BaseCheck.LOW
_VALID_LEVELS = frozenset({REQUIRED, RECOMMENDED, OPTIONAL})
_VALID_CV_STRICTNESS = frozenset({"error", "warn"})


@dataclass(frozen=True)
class AttrSpec:
    """
    A dataclass object storing the specifications for a single global attribute.

    Attributes
    ----------
    name : str
        The name of the global attribute.
    level : int
        The requirement level of the attribute (e.g., HIGH, MEDIUM, LOW).
    required_if : Optional[Callable], optional
        A callable that determines if the attribute is required based on a condition.
    cv : Optional[str], optional
        The controlled vocabulary associated with the attribute.
    cv_strictness : str, optional
        The strictness level for controlled vocabulary validation. Default is "warn".
    format_check : Optional[Callable[[str], bool]], optional
        A callable to check the format of the attribute's value. Default is None.
    format_hint : str, optional
        A hint for the expected format of the attribute's value. Default is "".
    """

    name: str
    level: int
    required_if: Optional[Callable] = None
    cv: Optional[str] = None
    cv_strictness: str = "warn"
    format_check: Optional[Callable[[str], bool]] = None
    format_hint: str = ""

    def __post_init__(self):
        # Validate the level and cv_strictness immediately after initialization
        if self.level not in _VALID_LEVELS:
            raise ValueError(
                f"level must be a Compliance Checker severity; got {self.level!r}"
            )
        if self.cv_strictness not in _VALID_CV_STRICTNESS:
            raise ValueError(
                "cv_strictness must be either 'error' or 'warn'; "
                f"got {self.cv_strictness!r}"
            )


def derive_global_attr_specs(
    reference: list[AttrSpec],
    *,
    add: Iterable[AttrSpec] = (),
    remove: Iterable[str] = (),
    update: Mapping[str, Mapping[str, object]] | None = None,
) -> list[AttrSpec]:
    """
    Produce a new list of AttrSpec objects from an existing AttrSpec list. Used when a
    new ODS version is released that requires modifications to the previous ODS version.

    Parameters
    ----------
    reference : list[AttrSpec]
        The existing list of AttrSpec objects used to derive an updated list.
    add : Iterable[AttrSpec], optional
        New AttrSpec objects to add.
    remove : Iterable[str], optional
        Names of existing AttrSpec objects to remove.
    update : Mapping[str, Mapping[str, object]], optional
        A mapping of AttrSpec names to dictionaries of field updates.

    Returns
    -------
    list[AttrSpec]
        An updated list of AttrSpec objects.

    Notes
    -----
    The function exists so that we don't have to copy and paste AttrSpec objects from
    a previous ODS version when creating specs for a new ODS version in
    ``cc_plugin_obs4mips/specs/ods_<version>.py.`` Usually a new ODS version will have
    only minor changes compared to the previous version, so this function helps to
    minimize duplication and potential errors. It adds/removes AttrSpecs but can also
    modify existing AttrSpecs.
    """
    by_name = {s.name: s for s in reference}
    for name in remove:
        by_name.pop(name, None)
    for name, changes in (update or {}).items():
        if name not in by_name:
            raise KeyError(f"can't update {name!r}: not present in reference spec")
        by_name[name] = replace(by_name[name], **changes)
    by_name.update({s.name: s for s in add})
    return list(by_name.values())
