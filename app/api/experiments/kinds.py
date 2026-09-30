"""Every capture experiment in the app, by slug."""

from . import data_collector, delay, scalability, temperature_change
from .base import Kind

KINDS: dict[str, Kind] = {
    k.slug: k
    for k in (data_collector.KIND, temperature_change.KIND, scalability.KIND, delay.KIND)
}
