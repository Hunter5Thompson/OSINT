"""Catalog-backed, static spatial-filter plans for CHRONIK reads."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal

from app.models.spatial import (
    CatalogProblemCode,
    ContainmentDescriptor,
    GeometryDescriptor,
    Lod,
    ScopeKind,
    ScopeNode,
    SpatialCatalogProblem,
    SpatialScopeTokenV1,
)
from app.models.timeline import (
    BBox,
    ChronikExactSpatialActivationV1,
    ChronikSpatialLane,
)
from app.services.spatial_catalog import ResolvedSpatialScope, SpatialCatalogLoader

_EPSILON = 1e-12
_GLOBAL_BBOX_PARAMETERS: dict[str, bool | float] = {
    "bbox_off": True,
    "west": -180.0,
    "east": 180.0,
    "south": -90.0,
    "north": 90.0,
}


class TimelineSpatialQueryId(StrEnum):
    """Allowlisted query shapes; catalog data can never supply query text."""

    GLOBAL = "timeline_global_v1"
    BBOX_SINGLE = "timeline_bbox_single_v1"
    BBOX_DATELINE = "timeline_bbox_dateline_v1"


class EventSpatialRelation(StrEnum):
    """Closed event relations supported by CHRONIK spatial templates."""

    OCCURS_IN = "occurs-in"
    INTERSECTS = "intersects"


class UnsupportedExactSpatialQueryError(ValueError):
    """The requested kind/relation pair has no reviewed static exact template."""


class ExactEventAccountingError(ValueError):
    """Exact query results violated the reviewed accounting contract."""


class ExactActivationRejectionCause(StrEnum):
    """Stable observability reasons for keeping a request on approximation."""

    NOT_CATALOG_SCOPED = "not_catalog_scoped"
    DEFAULT_OFF = "default_off"
    UNSUPPORTED_LANE = "unsupported_lane"
    UNSUPPORTED_SCOPE_KIND = "unsupported_scope_kind"
    LANE_KIND_NOT_ALLOWLISTED = "lane_kind_not_allowlisted"
    CONFIGURATION_INVALID = "configuration_invalid"
    DISABLED = "disabled"
    COVERAGE_INCOMPLETE = "coverage_incomplete"
    INDEX_PLAN_UNVERIFIED = "index_plan_unverified"
    STALE_REVISION_COVERAGE = "stale_revision_coverage"
    CATALOG_REVISION_MISMATCH = "catalog_revision_mismatch"
    DERIVATION_REVISION_MISMATCH = "derivation_revision_mismatch"


@dataclass(frozen=True, slots=True)
class ExactEventQueryTemplates:
    """Complete, immutable Cypher statements for one exact event query shape."""

    samples: str
    histogram: str
    notables: str
    incidents: str
    geo: str
    count: str


_EVENTS_COUNTRY_SCOPE_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.country_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH ev, l
ORDER BY CASE WHEN l.lat IS NOT NULL AND l.lon IS NOT NULL THEN 0 ELSE 1 END ASC,
         coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
LIMIT $limit
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       ev.title AS title, ev.codebook_type AS codebook_type, ev.severity AS severity,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       l.name AS location_name, l.country AS country, l.lat AS lat, l.lon AS lon
"""

_EVENTS_COUNTRY_SCOPE_COUNT_QUERY = """
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.country_scope_key = $scope_key
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
  RETURN count(DISTINCT ev) AS candidate_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.country_scope_key = $scope_key
    AND l.spatial_derivation_revision IN $compatible_revisions
    AND l.spatial_conflict = false
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
  RETURN count(DISTINCT ev) AS included_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.country_scope_key = $scope_key
    AND l.spatial_conflict = true
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
    AND NOT EXISTS {
      MATCH (valid:Location)<-[:OCCURRED_AT]-(ev)
      WHERE valid.country_scope_key = $scope_key
        AND valid.spatial_derivation_revision IN $compatible_revisions
        AND valid.spatial_conflict = false
    }
  RETURN count(DISTINCT ev) AS excluded_conflict_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.country_scope_key = $scope_key
    AND l.spatial_conflict = false
    AND (l.spatial_derivation_revision IS NULL
         OR NOT l.spatial_derivation_revision IN $compatible_revisions)
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
    AND NOT EXISTS {
      MATCH (valid:Location)<-[:OCCURRED_AT]-(ev)
      WHERE valid.country_scope_key = $scope_key
        AND valid.spatial_derivation_revision IN $compatible_revisions
        AND valid.spatial_conflict = false
    }
    AND NOT EXISTS {
      MATCH (conflict:Location)<-[:OCCURRED_AT]-(ev)
      WHERE conflict.country_scope_key = $scope_key
        AND conflict.spatial_conflict = true
    }
  RETURN count(DISTINCT ev) AS excluded_stale_revision_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.country_scope_key = $scope_key
    AND (l.spatial_conflict IS NULL
         OR NOT l.spatial_conflict IN [true, false])
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
    AND NOT EXISTS {
      MATCH (valid:Location)<-[:OCCURRED_AT]-(ev)
      WHERE valid.country_scope_key = $scope_key
        AND valid.spatial_derivation_revision IN $compatible_revisions
        AND valid.spatial_conflict = false
    }
    AND NOT EXISTS {
      MATCH (conflict:Location)<-[:OCCURRED_AT]-(ev)
      WHERE conflict.country_scope_key = $scope_key
        AND conflict.spatial_conflict = true
    }
    AND NOT EXISTS {
      MATCH (stale:Location)<-[:OCCURRED_AT]-(ev)
      WHERE stale.country_scope_key = $scope_key
        AND stale.spatial_conflict = false
        AND (stale.spatial_derivation_revision IS NULL
             OR NOT stale.spatial_derivation_revision IN $compatible_revisions)
    }
  RETURN count(DISTINCT ev) AS excluded_unsupported_count
}
RETURN candidate_count, included_count, excluded_conflict_count,
       excluded_stale_revision_count, excluded_unsupported_count
"""

_EVENTS_COUNTRY_SCOPE_HISTOGRAM_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.country_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH DISTINCT ev
RETURN toString(ev.timeline_at) AS time, ev.codebook_type AS codebook_type,
       ev.severity AS severity
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
"""

_EVENTS_COUNTRY_SCOPE_NOTABLES_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.country_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
  AND ev.severity IS NOT NULL
  AND toLower(trim(ev.severity)) IN ['high', 'elevated', 'critical', 'severe', 'extreme']
WITH ev, l
ORDER BY CASE WHEN l.lat IS NOT NULL AND l.lon IS NOT NULL THEN 0 ELSE 1 END ASC,
         coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       ev.severity AS severity, ev.title AS title, ev.codebook_type AS codebook_type,
       l.lat AS lat, l.lon AS lon
ORDER BY ev.timeline_at DESC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
LIMIT 400
"""

_INCIDENTS_COUNTRY_SCOPE_NOTABLES_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(i:Incident)
WHERE l.country_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND datetime(i.trigger_ts) >= datetime($t_start)
  AND datetime(i.trigger_ts) <= datetime($t_end)
WITH i, l
ORDER BY CASE WHEN l.lat IS NOT NULL AND l.lon IS NOT NULL THEN 0 ELSE 1 END ASC,
         coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH i, collect(l)[0] AS l
RETURN coalesce(i.id, toString(elementId(i))) AS id,
       toString(i.trigger_ts) AS time, 'occurred' AS time_basis,
       i.severity AS severity, i.title AS title, l.lat AS lat, l.lon AS lon
ORDER BY i.trigger_ts DESC, coalesce(i.id, toString(elementId(i))) ASC
LIMIT 200
"""

_EVENTS_COUNTRY_SCOPE_GEO_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.country_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND l.lat IS NOT NULL AND l.lon IS NOT NULL
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH ev, l
ORDER BY coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       toString(ev.timeline_at) AS time, ev.codebook_type AS codebook_type,
       ev.severity AS severity, l.lat AS lat, l.lon AS lon
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
"""

_EVENTS_ADMIN1_SCOPE_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin1_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH ev, l
ORDER BY CASE WHEN l.lat IS NOT NULL AND l.lon IS NOT NULL THEN 0 ELSE 1 END ASC,
         coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
LIMIT $limit
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       ev.title AS title, ev.codebook_type AS codebook_type, ev.severity AS severity,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       l.name AS location_name, l.country AS country, l.lat AS lat, l.lon AS lon
"""

_EVENTS_ADMIN1_SCOPE_COUNT_QUERY = """
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.admin1_scope_key = $scope_key
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
  RETURN count(DISTINCT ev) AS candidate_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.admin1_scope_key = $scope_key
    AND l.spatial_derivation_revision IN $compatible_revisions
    AND l.spatial_conflict = false
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
  RETURN count(DISTINCT ev) AS included_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.admin1_scope_key = $scope_key
    AND l.spatial_conflict = true
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
    AND NOT EXISTS {
      MATCH (valid:Location)<-[:OCCURRED_AT]-(ev)
      WHERE valid.admin1_scope_key = $scope_key
        AND valid.spatial_derivation_revision IN $compatible_revisions
        AND valid.spatial_conflict = false
    }
  RETURN count(DISTINCT ev) AS excluded_conflict_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.admin1_scope_key = $scope_key
    AND l.spatial_conflict = false
    AND (l.spatial_derivation_revision IS NULL
         OR NOT l.spatial_derivation_revision IN $compatible_revisions)
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
    AND NOT EXISTS {
      MATCH (valid:Location)<-[:OCCURRED_AT]-(ev)
      WHERE valid.admin1_scope_key = $scope_key
        AND valid.spatial_derivation_revision IN $compatible_revisions
        AND valid.spatial_conflict = false
    }
    AND NOT EXISTS {
      MATCH (conflict:Location)<-[:OCCURRED_AT]-(ev)
      WHERE conflict.admin1_scope_key = $scope_key
        AND conflict.spatial_conflict = true
    }
  RETURN count(DISTINCT ev) AS excluded_stale_revision_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.admin1_scope_key = $scope_key
    AND (l.spatial_conflict IS NULL
         OR NOT l.spatial_conflict IN [true, false])
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
    AND NOT EXISTS {
      MATCH (valid:Location)<-[:OCCURRED_AT]-(ev)
      WHERE valid.admin1_scope_key = $scope_key
        AND valid.spatial_derivation_revision IN $compatible_revisions
        AND valid.spatial_conflict = false
    }
    AND NOT EXISTS {
      MATCH (conflict:Location)<-[:OCCURRED_AT]-(ev)
      WHERE conflict.admin1_scope_key = $scope_key
        AND conflict.spatial_conflict = true
    }
    AND NOT EXISTS {
      MATCH (stale:Location)<-[:OCCURRED_AT]-(ev)
      WHERE stale.admin1_scope_key = $scope_key
        AND stale.spatial_conflict = false
        AND (stale.spatial_derivation_revision IS NULL
             OR NOT stale.spatial_derivation_revision IN $compatible_revisions)
    }
  RETURN count(DISTINCT ev) AS excluded_unsupported_count
}
RETURN candidate_count, included_count, excluded_conflict_count,
       excluded_stale_revision_count, excluded_unsupported_count
"""

_EVENTS_ADMIN1_SCOPE_HISTOGRAM_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin1_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH DISTINCT ev
RETURN toString(ev.timeline_at) AS time, ev.codebook_type AS codebook_type,
       ev.severity AS severity
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
"""

_EVENTS_ADMIN1_SCOPE_NOTABLES_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin1_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
  AND ev.severity IS NOT NULL
  AND toLower(trim(ev.severity)) IN ['high', 'elevated', 'critical', 'severe', 'extreme']
WITH ev, l
ORDER BY CASE WHEN l.lat IS NOT NULL AND l.lon IS NOT NULL THEN 0 ELSE 1 END ASC,
         coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       ev.severity AS severity, ev.title AS title, ev.codebook_type AS codebook_type,
       l.lat AS lat, l.lon AS lon
ORDER BY ev.timeline_at DESC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
LIMIT 400
"""

_INCIDENTS_ADMIN1_SCOPE_NOTABLES_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(i:Incident)
WHERE l.admin1_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND datetime(i.trigger_ts) >= datetime($t_start)
  AND datetime(i.trigger_ts) <= datetime($t_end)
WITH i, l
ORDER BY CASE WHEN l.lat IS NOT NULL AND l.lon IS NOT NULL THEN 0 ELSE 1 END ASC,
         coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH i, collect(l)[0] AS l
RETURN coalesce(i.id, toString(elementId(i))) AS id,
       toString(i.trigger_ts) AS time, 'occurred' AS time_basis,
       i.severity AS severity, i.title AS title, l.lat AS lat, l.lon AS lon
ORDER BY i.trigger_ts DESC, coalesce(i.id, toString(elementId(i))) ASC
LIMIT 200
"""

_EVENTS_ADMIN1_SCOPE_GEO_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin1_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND l.lat IS NOT NULL AND l.lon IS NOT NULL
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH ev, l
ORDER BY coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       toString(ev.timeline_at) AS time, ev.codebook_type AS codebook_type,
       ev.severity AS severity, l.lat AS lat, l.lon AS lon
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
"""

_EVENTS_ADMIN2_SCOPE_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin2_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH ev, l
ORDER BY CASE WHEN l.lat IS NOT NULL AND l.lon IS NOT NULL THEN 0 ELSE 1 END ASC,
         coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
LIMIT $limit
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       ev.title AS title, ev.codebook_type AS codebook_type, ev.severity AS severity,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       l.name AS location_name, l.country AS country, l.lat AS lat, l.lon AS lon
"""

_EVENTS_ADMIN2_SCOPE_COUNT_QUERY = """
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.admin2_scope_key = $scope_key
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
  RETURN count(DISTINCT ev) AS candidate_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.admin2_scope_key = $scope_key
    AND l.spatial_derivation_revision IN $compatible_revisions
    AND l.spatial_conflict = false
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
  RETURN count(DISTINCT ev) AS included_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.admin2_scope_key = $scope_key
    AND l.spatial_conflict = true
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
    AND NOT EXISTS {
      MATCH (valid:Location)<-[:OCCURRED_AT]-(ev)
      WHERE valid.admin2_scope_key = $scope_key
        AND valid.spatial_derivation_revision IN $compatible_revisions
        AND valid.spatial_conflict = false
    }
  RETURN count(DISTINCT ev) AS excluded_conflict_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.admin2_scope_key = $scope_key
    AND l.spatial_conflict = false
    AND (l.spatial_derivation_revision IS NULL
         OR NOT l.spatial_derivation_revision IN $compatible_revisions)
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
    AND NOT EXISTS {
      MATCH (valid:Location)<-[:OCCURRED_AT]-(ev)
      WHERE valid.admin2_scope_key = $scope_key
        AND valid.spatial_derivation_revision IN $compatible_revisions
        AND valid.spatial_conflict = false
    }
    AND NOT EXISTS {
      MATCH (conflict:Location)<-[:OCCURRED_AT]-(ev)
      WHERE conflict.admin2_scope_key = $scope_key
        AND conflict.spatial_conflict = true
    }
  RETURN count(DISTINCT ev) AS excluded_stale_revision_count
}
CALL () {
  MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
  WHERE l.admin2_scope_key = $scope_key
    AND (l.spatial_conflict IS NULL
         OR NOT l.spatial_conflict IN [true, false])
    AND ev.timeline_at >= datetime($t_start)
    AND ev.timeline_at <= datetime($t_end)
    AND NOT EXISTS {
      MATCH (valid:Location)<-[:OCCURRED_AT]-(ev)
      WHERE valid.admin2_scope_key = $scope_key
        AND valid.spatial_derivation_revision IN $compatible_revisions
        AND valid.spatial_conflict = false
    }
    AND NOT EXISTS {
      MATCH (conflict:Location)<-[:OCCURRED_AT]-(ev)
      WHERE conflict.admin2_scope_key = $scope_key
        AND conflict.spatial_conflict = true
    }
    AND NOT EXISTS {
      MATCH (stale:Location)<-[:OCCURRED_AT]-(ev)
      WHERE stale.admin2_scope_key = $scope_key
        AND stale.spatial_conflict = false
        AND (stale.spatial_derivation_revision IS NULL
             OR NOT stale.spatial_derivation_revision IN $compatible_revisions)
    }
  RETURN count(DISTINCT ev) AS excluded_unsupported_count
}
RETURN candidate_count, included_count, excluded_conflict_count,
       excluded_stale_revision_count, excluded_unsupported_count
"""

_EVENTS_ADMIN2_SCOPE_HISTOGRAM_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin2_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH DISTINCT ev
RETURN toString(ev.timeline_at) AS time, ev.codebook_type AS codebook_type,
       ev.severity AS severity
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
"""

_EVENTS_ADMIN2_SCOPE_NOTABLES_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin2_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
  AND ev.severity IS NOT NULL
  AND toLower(trim(ev.severity)) IN ['high', 'elevated', 'critical', 'severe', 'extreme']
WITH ev, l
ORDER BY CASE WHEN l.lat IS NOT NULL AND l.lon IS NOT NULL THEN 0 ELSE 1 END ASC,
         coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       toString(ev.timeline_at) AS time, ev.time_basis AS time_basis,
       ev.severity AS severity, ev.title AS title, ev.codebook_type AS codebook_type,
       l.lat AS lat, l.lon AS lon
ORDER BY ev.timeline_at DESC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
LIMIT 400
"""

_INCIDENTS_ADMIN2_SCOPE_NOTABLES_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(i:Incident)
WHERE l.admin2_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND datetime(i.trigger_ts) >= datetime($t_start)
  AND datetime(i.trigger_ts) <= datetime($t_end)
WITH i, l
ORDER BY CASE WHEN l.lat IS NOT NULL AND l.lon IS NOT NULL THEN 0 ELSE 1 END ASC,
         coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH i, collect(l)[0] AS l
RETURN coalesce(i.id, toString(elementId(i))) AS id,
       toString(i.trigger_ts) AS time, 'occurred' AS time_basis,
       i.severity AS severity, i.title AS title, l.lat AS lat, l.lon AS lon
ORDER BY i.trigger_ts DESC, coalesce(i.id, toString(elementId(i))) ASC
LIMIT 200
"""

_EVENTS_ADMIN2_SCOPE_GEO_QUERY = """
MATCH (l:Location)<-[:OCCURRED_AT]-(ev:Event)
WHERE l.admin2_scope_key = $scope_key
  AND l.spatial_derivation_revision IN $compatible_revisions
  AND l.spatial_conflict = false
  AND l.lat IS NOT NULL AND l.lon IS NOT NULL
  AND ev.timeline_at >= datetime($t_start)
  AND ev.timeline_at <= datetime($t_end)
WITH ev, l
ORDER BY coalesce(l.id, l.location_id, l.name, elementId(l)) ASC
WITH ev, collect(l)[0] AS l
RETURN coalesce(ev.id, ev.event_id, toString(elementId(ev))) AS id,
       toString(ev.timeline_at) AS time, ev.codebook_type AS codebook_type,
       ev.severity AS severity, l.lat AS lat, l.lon AS lon
ORDER BY ev.timeline_at ASC,
         coalesce(ev.id, ev.event_id, toString(elementId(ev))) ASC
"""

_EXACT_EVENT_QUERY_REGISTRY: Final[
    Mapping[tuple[ScopeKind, EventSpatialRelation], ExactEventQueryTemplates]
] = MappingProxyType(
    {
        (ScopeKind.COUNTRY, EventSpatialRelation.OCCURS_IN): ExactEventQueryTemplates(
            samples=_EVENTS_COUNTRY_SCOPE_QUERY,
            histogram=_EVENTS_COUNTRY_SCOPE_HISTOGRAM_QUERY,
            notables=_EVENTS_COUNTRY_SCOPE_NOTABLES_QUERY,
            incidents=_INCIDENTS_COUNTRY_SCOPE_NOTABLES_QUERY,
            geo=_EVENTS_COUNTRY_SCOPE_GEO_QUERY,
            count=_EVENTS_COUNTRY_SCOPE_COUNT_QUERY,
        ),
        (ScopeKind.ADMIN1, EventSpatialRelation.OCCURS_IN): ExactEventQueryTemplates(
            samples=_EVENTS_ADMIN1_SCOPE_QUERY,
            histogram=_EVENTS_ADMIN1_SCOPE_HISTOGRAM_QUERY,
            notables=_EVENTS_ADMIN1_SCOPE_NOTABLES_QUERY,
            incidents=_INCIDENTS_ADMIN1_SCOPE_NOTABLES_QUERY,
            geo=_EVENTS_ADMIN1_SCOPE_GEO_QUERY,
            count=_EVENTS_ADMIN1_SCOPE_COUNT_QUERY,
        ),
        (ScopeKind.ADMIN2, EventSpatialRelation.OCCURS_IN): ExactEventQueryTemplates(
            samples=_EVENTS_ADMIN2_SCOPE_QUERY,
            histogram=_EVENTS_ADMIN2_SCOPE_HISTOGRAM_QUERY,
            notables=_EVENTS_ADMIN2_SCOPE_NOTABLES_QUERY,
            incidents=_INCIDENTS_ADMIN2_SCOPE_NOTABLES_QUERY,
            geo=_EVENTS_ADMIN2_SCOPE_GEO_QUERY,
            count=_EVENTS_ADMIN2_SCOPE_COUNT_QUERY,
        ),
    }
)


def exact_event_query_templates(
    scope_kind: ScopeKind,
    relation: EventSpatialRelation,
) -> ExactEventQueryTemplates:
    """Return only a reviewed complete template pair for enum-selected inputs."""

    if not isinstance(scope_kind, ScopeKind) or not isinstance(
        relation,
        EventSpatialRelation,
    ):
        raise UnsupportedExactSpatialQueryError("exact spatial query is unsupported")
    try:
        return _EXACT_EVENT_QUERY_REGISTRY[(scope_kind, relation)]
    except KeyError as exc:
        raise UnsupportedExactSpatialQueryError(
            f"exact event query is unsupported for {scope_kind.value}/{relation.value}"
        ) from exc


@dataclass(frozen=True, slots=True, order=True)
class LongitudeSpan:
    west: float
    east: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.west, bool)
            or isinstance(self.east, bool)
            or not math.isfinite(self.west)
            or not math.isfinite(self.east)
            or not -180 <= self.west <= self.east <= 180
        ):
            raise ValueError("longitude span must be finite and non-wrapping")


@dataclass(frozen=True, slots=True)
class GeoExtent:
    kind: Literal["world", "segments"]
    south: float | None = None
    north: float | None = None
    longitude: tuple[LongitudeSpan, ...] = ()

    def __post_init__(self) -> None:
        if self.kind == "world":
            if self.south is not None or self.north is not None or self.longitude:
                raise ValueError("world extent does not carry segment fields")
            return
        if self.kind != "segments":
            raise ValueError("unknown extent kind")
        if (
            self.south is None
            or self.north is None
            or isinstance(self.south, bool)
            or isinstance(self.north, bool)
            or not math.isfinite(self.south)
            or not math.isfinite(self.north)
            or not -90 <= self.south <= self.north <= 90
            or not 1 <= len(self.longitude) <= 2
        ):
            raise ValueError("invalid segmented extent")


@dataclass(frozen=True, slots=True)
class ResolvedSpatialConstraint:
    token: SpatialScopeTokenV1
    extent: GeoExtent
    country_scope_key: str | None
    admin1_scope_key: str | None
    admin2_scope_key: str | None


@dataclass(frozen=True, slots=True)
class CompiledSpatialFilter:
    query_id: TimelineSpatialQueryId
    parameters: Mapping[str, bool | float]
    bbox: BBox | None
    constraint: ResolvedSpatialConstraint | None = None


@dataclass(frozen=True, slots=True)
class ExactEventQueryPlan:
    """Pinned token plus reviewed exact templates and their coverage decision."""

    spatial_filter: CompiledSpatialFilter
    templates: ExactEventQueryTemplates
    coverage_revision: str
    coverage_complete: bool

    def __post_init__(self) -> None:
        if self.spatial_filter.constraint is None:
            raise ValueError("exact event query requires a resolved spatial token")
        if not self.coverage_revision:
            raise ValueError("exact event query requires a coverage revision")


@dataclass(frozen=True, slots=True)
class ExactEventAccounting:
    """Reconciled distinct-record accounting returned by one exact count query."""

    candidate_count: int
    included_count: int
    sample_count: int
    excluded_unlocated_count: int
    excluded_conflict_count: int
    excluded_stale_revision_count: int
    excluded_unsupported_count: int


@dataclass(frozen=True, slots=True)
class ExactEventActivationDecision:
    """Fail-closed result of applying deployment data to one resolved request."""

    approximate_filter: CompiledSpatialFilter
    plan: ExactEventQueryPlan | None
    cause: ExactActivationRejectionCause | None
    activation: ChronikExactSpatialActivationV1 | None


type CatalogFilterResolution = CompiledSpatialFilter | SpatialCatalogProblem


def compile_exact_event_query_plan(
    spatial_filter: CompiledSpatialFilter,
    *,
    coverage_revision: str,
    coverage_complete: bool,
) -> ExactEventQueryPlan:
    """Compile exact occurrence reads from one already resolved catalog token."""

    constraint = spatial_filter.constraint
    if constraint is None:
        raise UnsupportedExactSpatialQueryError(
            "exact event query requires a catalog-pinned scope"
        )
    templates = exact_event_query_templates(
        constraint.token.kind,
        EventSpatialRelation.OCCURS_IN,
    )
    return ExactEventQueryPlan(
        spatial_filter=spatial_filter,
        templates=templates,
        coverage_revision=coverage_revision,
        coverage_complete=coverage_complete,
    )


def select_exact_event_activation(
    spatial_filter: CompiledSpatialFilter,
    *,
    lane: ChronikSpatialLane,
    activations: Sequence[ChronikExactSpatialActivationV1],
    max_stale_revision_ratio: float,
) -> ExactEventActivationDecision:
    """Select one matching revision from the server-owned lane/kind set."""

    constraint = spatial_filter.constraint
    if constraint is None:
        return _rejected_activation(
            spatial_filter,
            ExactActivationRejectionCause.NOT_CATALOG_SCOPED,
        )
    if lane is not ChronikSpatialLane.EVENT_OCCURRENCE:
        return _rejected_activation(
            spatial_filter,
            ExactActivationRejectionCause.UNSUPPORTED_LANE,
        )
    token = constraint.token
    if token.kind not in {ScopeKind.COUNTRY, ScopeKind.ADMIN1, ScopeKind.ADMIN2}:
        return _rejected_activation(
            spatial_filter,
            ExactActivationRejectionCause.UNSUPPORTED_SCOPE_KIND,
        )
    if not activations:
        return _rejected_activation(
            spatial_filter,
            ExactActivationRejectionCause.DEFAULT_OFF,
        )

    lane_kind_matches = tuple(
        activation
        for activation in activations
        if activation.lane is lane and activation.scope_kind is token.kind
    )
    if not lane_kind_matches:
        return _rejected_activation(
            spatial_filter,
            ExactActivationRejectionCause.LANE_KIND_NOT_ALLOWLISTED,
        )
    enabled_derivation_revisions = {
        activation.derivation_revision for activation in lane_kind_matches
    }
    if token.derivation_revision not in enabled_derivation_revisions:
        return _rejected_activation(
            spatial_filter,
            ExactActivationRejectionCause.DERIVATION_REVISION_MISMATCH,
        )
    matches = tuple(
        activation
        for activation in lane_kind_matches
        if activation.derivation_revision == token.derivation_revision
    )
    if len(matches) != 1:
        return _rejected_activation(
            spatial_filter,
            ExactActivationRejectionCause.CONFIGURATION_INVALID,
        )
    activation = matches[0]
    checks = (
        (activation.enabled, ExactActivationRejectionCause.DISABLED),
        (
            activation.coverage_complete,
            ExactActivationRejectionCause.COVERAGE_INCOMPLETE,
        ),
        (
            activation.index_plan_verified,
            ExactActivationRejectionCause.INDEX_PLAN_UNVERIFIED,
        ),
        (
            activation.stale_revision_ratio <= max_stale_revision_ratio,
            ExactActivationRejectionCause.STALE_REVISION_COVERAGE,
        ),
        (
            activation.catalog_revision == token.catalog_revision,
            ExactActivationRejectionCause.CATALOG_REVISION_MISMATCH,
        ),
    )
    for accepted, cause in checks:
        if not accepted:
            return _rejected_activation(spatial_filter, cause, activation)

    return ExactEventActivationDecision(
        approximate_filter=spatial_filter,
        plan=compile_exact_event_query_plan(
            spatial_filter,
            coverage_revision=str(activation.coverage_revision),
            coverage_complete=activation.coverage_complete,
        ),
        cause=None,
        activation=activation,
    )


def _rejected_activation(
    spatial_filter: CompiledSpatialFilter,
    cause: ExactActivationRejectionCause,
    activation: ChronikExactSpatialActivationV1 | None = None,
) -> ExactEventActivationDecision:
    return ExactEventActivationDecision(
        approximate_filter=spatial_filter,
        plan=None,
        cause=cause,
        activation=activation,
    )


def exact_event_parameters(
    plan: ExactEventQueryPlan,
    *,
    t_start: str,
    t_end: str,
    limit: int,
) -> dict[str, object]:
    """Bind all values for exact Cypher without exposing a query-text seam."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("exact event limit must be a positive integer")
    constraint = plan.spatial_filter.constraint
    assert constraint is not None
    token = constraint.token
    return {
        "scope_key": str(token.scope_key),
        "compatible_revisions": [str(value) for value in token.compatible_derivation_revisions],
        "t_start": t_start,
        "t_end": t_end,
        "limit": limit,
    }


def parse_exact_event_accounting(
    rows: Sequence[Mapping[str, object]],
    *,
    sample_count: int,
) -> ExactEventAccounting:
    """Validate that exact distinct-record categories are disjoint and complete."""

    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 0:
        raise ExactEventAccountingError(
            "exact sample count must be a non-negative integer"
        )
    if len(rows) != 1:
        raise ExactEventAccountingError(
            "exact accounting must return exactly one row"
        )
    row = rows[0]
    counts = {
        field: _strict_non_negative_int(row.get(field), field)
        for field in (
            "candidate_count",
            "included_count",
            "excluded_conflict_count",
            "excluded_stale_revision_count",
            "excluded_unsupported_count",
        )
    }
    reconciled = sum(
        value for field, value in counts.items() if field != "candidate_count"
    )
    if counts["candidate_count"] != reconciled:
        raise ExactEventAccountingError(
            "exact accounting categories do not reconcile"
        )
    if sample_count > counts["included_count"]:
        raise ExactEventAccountingError(
            "exact samples exceed distinct included records"
        )
    return ExactEventAccounting(
        candidate_count=counts["candidate_count"],
        included_count=counts["included_count"],
        sample_count=sample_count,
        excluded_unlocated_count=0,
        excluded_conflict_count=counts["excluded_conflict_count"],
        excluded_stale_revision_count=counts["excluded_stale_revision_count"],
        excluded_unsupported_count=counts["excluded_unsupported_count"],
    )


def _strict_non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExactEventAccountingError(
            f"{field} must be a non-negative integer"
        )
    return value


def compile_extent_filter(
    extent: GeoExtent,
    *,
    constraint: ResolvedSpatialConstraint | None = None,
) -> CompiledSpatialFilter:
    """Project one reviewed extent to the existing timeline BBox convention."""

    if extent.kind == "world":
        return CompiledSpatialFilter(
            query_id=TimelineSpatialQueryId.GLOBAL,
            parameters=dict(_GLOBAL_BBOX_PARAMETERS),
            bbox=None,
            constraint=constraint,
        )

    assert extent.south is not None
    assert extent.north is not None
    spans = tuple(sorted(extent.longitude))
    if len(spans) == 1:
        span = spans[0]
        bbox = BBox(
            west=span.west,
            south=extent.south,
            east=span.east,
            north=extent.north,
        )
        return CompiledSpatialFilter(
            query_id=TimelineSpatialQueryId.BBOX_SINGLE,
            parameters=_bbox_parameters(bbox),
            bbox=bbox,
            constraint=constraint,
        )

    western, eastern = spans
    if (
        not math.isclose(western.west, -180.0, abs_tol=_EPSILON)
        or not math.isclose(eastern.east, 180.0, abs_tol=_EPSILON)
        or western.east >= eastern.west
    ):
        raise ValueError("two-span extent must be a canonical dateline extent")
    bbox = BBox(
        west=eastern.west,
        south=extent.south,
        east=western.east,
        north=extent.north,
    )
    return CompiledSpatialFilter(
        query_id=TimelineSpatialQueryId.BBOX_DATELINE,
        parameters=_bbox_parameters(bbox),
        bbox=bbox,
        constraint=constraint,
    )


def compile_legacy_bbox_filter(bbox: BBox | None) -> CompiledSpatialFilter:
    """Keep the explicit viewport/AOI BBox as a separate, tokenless request mode."""

    if bbox is None:
        return compile_extent_filter(GeoExtent(kind="world"))
    longitude = (
        (LongitudeSpan(bbox.west, bbox.east),)
        if bbox.west <= bbox.east
        else (
            LongitudeSpan(-180.0, bbox.east),
            LongitudeSpan(bbox.west, 180.0),
        )
    )
    return compile_extent_filter(
        GeoExtent(
            kind="segments",
            south=bbox.south,
            north=bbox.north,
            longitude=longitude,
        )
    )


def extent_from_boundary_geometry(payload: bytes | object) -> GeoExtent:
    """Validate a BoundaryGeometryV1 value and derive its circular extent."""

    value = _decode_json(payload)
    geometry = _mapping(value, "boundary geometry")
    if set(geometry) != {"schema_version", "geometry_type", "polygons"}:
        raise ValueError("boundary geometry has unknown or missing fields")
    if geometry.get("schema_version") != 1 or geometry.get("geometry_type") != "MultiPolygon":
        raise ValueError("boundary geometry schema is unsupported")

    polygons = _sequence(geometry.get("polygons"), "polygons")
    if not polygons:
        raise ValueError("boundary geometry has no polygons")
    longitudes: list[float] = []
    latitudes: list[float] = []
    full_longitude = False
    for polygon_index, polygon_value in enumerate(polygons):
        polygon = _sequence(polygon_value, f"polygon[{polygon_index}]")
        if not polygon:
            raise ValueError("polygon has no rings")
        for ring_index, ring_value in enumerate(polygon):
            ring = _sequence(ring_value, f"ring[{ring_index}]")
            if len(ring) < 4:
                raise ValueError("boundary ring is too short")
            positions = tuple(
                _position(position, f"position[{position_index}]")
                for position_index, position in enumerate(ring)
            )
            if positions[0] != positions[-1]:
                raise ValueError("boundary ring is not closed")
            full_longitude = full_longitude or any(
                math.isclose(abs(right[0] - left[0]), 360.0, abs_tol=_EPSILON)
                for left, right in zip(positions, positions[1:], strict=False)
            )
            for position_longitude, latitude in positions[:-1]:
                longitudes.append(position_longitude)
                latitudes.append(latitude)

    if not longitudes or not latitudes:
        raise ValueError("boundary geometry has no positions")
    longitude_spans = (
        (LongitudeSpan(-180.0, 180.0),)
        if full_longitude
        else _minimal_longitude_spans(tuple(longitudes))
    )
    return GeoExtent(
        kind="segments",
        south=min(latitudes),
        north=max(latitudes),
        longitude=longitude_spans,
    )


async def resolve_catalog_filter(
    loader: SpatialCatalogLoader,
    scope_key: str,
    catalog_revision: str,
) -> CatalogFilterResolution:
    """Resolve exactly one catalog token and compile its boundary extent fail-closed."""

    resolved = loader.resolve_scope(scope_key, catalog_revision)
    if isinstance(resolved, SpatialCatalogProblem):
        return resolved

    record = resolved.record
    token = SpatialScopeTokenV1(
        scope_key=record.scope.key,
        kind=record.scope.kind,
        catalog_revision=resolved.catalog_revision,
        derivation_revision=record.derivation_revision,
        boundary_policy=resolved.boundary_policy,
        compatible_derivation_revisions=record.compatible_derivation_revisions,
    )
    if token.kind is ScopeKind.WORLD:
        extent = GeoExtent(kind="world")
        constraint = _constraint(token, extent, resolved.path)
        return compile_extent_filter(extent, constraint=constraint)

    try:
        extent_or_problem = await _resolve_non_global_extent(loader, resolved)
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return _filter_unavailable(scope_key, catalog_revision)
    if isinstance(extent_or_problem, SpatialCatalogProblem):
        return extent_or_problem
    constraint = _constraint(token, extent_or_problem, resolved.path)
    try:
        return compile_extent_filter(extent_or_problem, constraint=constraint)
    except ValueError:
        return _filter_unavailable(scope_key, catalog_revision)


async def _resolve_non_global_extent(
    loader: SpatialCatalogLoader,
    resolved: ResolvedSpatialScope,
) -> GeoExtent | SpatialCatalogProblem:
    record = resolved.record
    revision = resolved.catalog_revision
    presentation = record.presentation

    descriptor: GeometryDescriptor | ContainmentDescriptor | None = presentation.containment
    if descriptor is None and presentation.outline_lods:
        descriptor = _preferred_or_first_descriptor(
            presentation.outline_lods,
            presentation.preferred_lod,
        )
    if descriptor is not None:
        payload = await _read_catalog_asset(loader, revision, descriptor.asset_id)
        if isinstance(payload, SpatialCatalogProblem):
            return payload
        return extent_from_boundary_geometry(payload)

    parent_key = record.scope.parent_key
    if parent_key is None:
        raise ValueError("non-global scope has no parent geometry source")
    parent = loader.get_scope(revision, parent_key)
    if isinstance(parent, SpatialCatalogProblem):
        return parent
    parent_presentation = parent.presentation
    descriptor = _preferred_or_first_descriptor(
        parent_presentation.children_lods,
        parent_presentation.preferred_lod,
    )
    payload = await _read_catalog_asset(loader, revision, descriptor.asset_id)
    if isinstance(payload, SpatialCatalogProblem):
        return payload
    return _extent_from_boundary_pack(
        payload,
        parent_scope_key=parent_key,
        scope_key=record.scope.key,
    )


async def _read_catalog_asset(
    loader: SpatialCatalogLoader,
    revision: str,
    asset_id: str,
) -> bytes | SpatialCatalogProblem:
    asset = loader.get_asset(revision, asset_id)
    if isinstance(asset, SpatialCatalogProblem):
        return asset
    return await loader.read_asset(asset)


def _preferred_or_first_descriptor(
    descriptors: Mapping[Lod, GeometryDescriptor],
    preferred: Lod | None,
) -> GeometryDescriptor:
    if preferred is not None:
        descriptor = descriptors.get(preferred)
        if descriptor is not None:
            return descriptor
    if not descriptors:
        raise ValueError("catalog scope has no boundary descriptor")
    first_key = min(descriptors, key=str)
    return descriptors[first_key]


def _extent_from_boundary_pack(
    payload: bytes,
    *,
    parent_scope_key: str,
    scope_key: str,
) -> GeoExtent:
    pack = _mapping(_decode_json(payload), "boundary pack")
    if set(pack) != {"schema_version", "parent_scope_key", "features"}:
        raise ValueError("boundary pack has unknown or missing fields")
    if pack.get("schema_version") != 1 or pack.get("parent_scope_key") != parent_scope_key:
        raise ValueError("boundary pack identity is invalid")
    features = _sequence(pack.get("features"), "features")
    for feature_value in features:
        feature = _mapping(feature_value, "boundary feature")
        if feature.get("kind") != "scope" or feature.get("scope_key") != scope_key:
            continue
        if set(feature) != {"kind", "scope_key", "label", "geometry"}:
            raise ValueError("scope feature has unknown or missing fields")
        return extent_from_boundary_geometry(feature.get("geometry"))
    raise ValueError("scope geometry is absent from its parent boundary pack")


def _constraint(
    token: SpatialScopeTokenV1,
    extent: GeoExtent,
    path: Sequence[ScopeNode],
) -> ResolvedSpatialConstraint:
    keys_by_kind = {
        node.kind: str(node.key)
        for node in path
    }
    return ResolvedSpatialConstraint(
        token=token,
        extent=extent,
        country_scope_key=keys_by_kind.get(ScopeKind.COUNTRY),
        admin1_scope_key=keys_by_kind.get(ScopeKind.ADMIN1),
        admin2_scope_key=keys_by_kind.get(ScopeKind.ADMIN2),
    )


def _bbox_parameters(bbox: BBox) -> dict[str, bool | float]:
    return {
        "bbox_off": False,
        "west": bbox.west,
        "east": bbox.east,
        "south": bbox.south,
        "north": bbox.north,
    }


def _minimal_longitude_spans(longitudes: tuple[float, ...]) -> tuple[LongitudeSpan, ...]:
    angles = sorted({(longitude + 180) % 360 for longitude in longitudes})
    if len(angles) == 1:
        longitude = _clean_longitude(angles[0] - 180)
        return (LongitudeSpan(longitude, longitude),)
    gaps = [
        (((angles[(index + 1) % len(angles)] - angle) % 360), index)
        for index, angle in enumerate(angles)
    ]
    _, gap_index = max(gaps, key=lambda item: (item[0], -item[1]))
    start_angle = angles[(gap_index + 1) % len(angles)]
    end_angle = angles[gap_index]
    if end_angle < start_angle:
        end_angle += 360
    west = _clean_longitude(start_angle - 180)
    east_unwrapped = end_angle - 180
    if east_unwrapped <= 180 + _EPSILON:
        return (LongitudeSpan(west, _clean_longitude(min(east_unwrapped, 180))),)
    return (
        LongitudeSpan(-180.0, _clean_longitude(east_unwrapped - 360)),
        LongitudeSpan(west, 180.0),
    )


def _position(value: object, context: str) -> tuple[float, float]:
    position = _sequence(value, context)
    if len(position) != 2:
        raise ValueError(f"{context} must have two coordinates")
    longitude = _finite_number(position[0], f"{context}.longitude")
    latitude = _finite_number(position[1], f"{context}.latitude")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError(f"{context} is outside WGS84 ranges")
    return longitude, latitude


def _finite_number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{context} must be finite")
    return converted


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return value


def _sequence(value: object, context: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{context} must be an array")
    return value


def _decode_json(payload: bytes | object) -> object:
    if isinstance(payload, bytes):
        return json.loads(payload)
    return payload


def _clean_longitude(value: float) -> float:
    value = round(value, 12)
    if math.isclose(value, -180.0, abs_tol=_EPSILON):
        return -180.0
    if math.isclose(value, 180.0, abs_tol=_EPSILON):
        return 180.0
    return 0.0 if math.isclose(value, 0.0, abs_tol=_EPSILON) else value


def _filter_unavailable(scope_key: str, revision: str) -> SpatialCatalogProblem:
    return SpatialCatalogProblem(
        code=CatalogProblemCode.SPATIAL_FILTER_UNAVAILABLE,
        message="Spatial timeline filter is unavailable",
        target=scope_key,
        recoverable=True,
        active_catalog_revision=revision,
    )
