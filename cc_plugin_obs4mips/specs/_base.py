from dataclasses import dataclass, replace
from typing import Callable, Iterable, Mapping, Optional


@dataclass(frozen=True)
class AttrSpec:
    """
    Specification for a single attribute, including its name, requirement level,
    conditional requirements, CV validation, and format checks.
    """

    name: str
    level: int
    required_if: Optional[Callable] = None
    cv: Optional[str] = None
    cv_strictness: str = "warn"
    format_check: Optional[Callable[[str], bool]] = None
    format_hint: str = ""


def derive_spec(
    base: list[AttrSpec],
    *,
    add: Iterable[AttrSpec] = (),
    remove: Iterable[str] = (),
    update: Mapping[str, dict] = None,  # type: ignore
) -> list[AttrSpec]:
    """
    Produce a new spec list from `base` with additions, removals, and field updates. Use
    for ODS-version-to-version diffs so each version file reads as a changelog.
    """
    by_name = {s.name: s for s in base}
    for name in remove:
        by_name.pop(name, None)
    for name, changes in (update or {}).items():
        if name not in by_name:
            raise KeyError(f"can't update {name!r}: not present in base spec")
        by_name[name] = replace(by_name[name], **changes)
    by_name.update({s.name: s for s in add})
    return list(by_name.values())
