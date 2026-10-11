"""Entity history features, PAST ONLY (the current row is never part of its own history).

Two implementations of the same definitions:
- batch_history: vectorised over a TransactionDT-sorted frame (parquet pipeline);
- EntityStore: per-entity running state used by transform_one (API) and saved to
  artifacts/entity_profiles.parquet.
tests/features/test_batch_online_equality.py checks that both give the same numbers.

Window rule: a past event counts for window w when event_dt >= dt - w (ties in time are
ordered by row position; only earlier rows are past).
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.features.learned import LearnedStats
from src.features.utils import NA_KEY

BIG = 10**9  # separates entities in the combined (entity, time) sort key; > any dt + window


def small_streak_name(cfg: dict) -> str:
    """Name of the small-amount streak feature; its window must be one of the velocity windows."""
    window = cfg["small_amount"]["window"]
    if window not in cfg["windows"]:
        raise ValueError(
            f"small_amount.window '{window}' is not a velocity window {list(cfg['windows'])}"
        )
    return f"small_amt_streak_{window}"


def history_columns(cfg: dict) -> list[str]:
    """Names of the history features in output order."""
    window_names = list(cfg["windows"])
    cols = [
        "is_first_seen",
        "ent_txn_count",
        "ent_avg_amt",
        "ent_std_amt",
        "ent_max_amt",
        "amt_ratio_to_ent_avg",
        "amt_zscore_ent",
        "ent_age_days",
        "ent_unique_device",
        "ent_unique_email",
        "time_since_last_txn",
        "avg_inter_arrival",
    ]
    cols += [f"ent_cnt_{w}" for w in window_names]
    cols += [f"ent_sum_{w}" for w in window_names]
    cols += [small_streak_name(cfg), "card_new_addr", "device_ent_match"]
    return cols


def _derived(
    n: np.ndarray,
    ssum: np.ndarray,
    ssq: np.ndarray,
    amt: np.ndarray,
    L: LearnedStats,
    z_floor: float,
) -> dict[str, np.ndarray]:
    """avg / std / ratio / z from running sums of (amount - amt_mean). Shared by both paths."""
    safe_n = np.maximum(n, 1)
    mean = np.where(n >= 1, L.amt_mean + ssum / safe_n, L.amt_mean)
    var = (ssq - ssum**2 / safe_n) / np.maximum(n - 1, 1)
    std = np.where(n >= 2, np.sqrt(np.maximum(var, 0.0)), L.amt_std)
    ratio = np.where((n >= 1) & (mean > 0), amt / np.where(mean > 0, mean, 1.0), 1.0)
    z = np.where(n >= 2, (amt - mean) / np.maximum(std, z_floor), 0.0)
    return {
        "ent_avg_amt": mean,
        "ent_std_amt": std,
        "amt_ratio_to_ent_avg": ratio,
        "amt_zscore_ent": z,
    }


def batch_history(
    ent: np.ndarray,
    card: np.ndarray,
    dev: np.ndarray,
    email: np.ndarray,
    dt: np.ndarray,
    amt: np.ndarray,
    L: LearnedStats,
    cfg: dict,
) -> pd.DataFrame:
    """History features for rows ALREADY sorted by TransactionDT (stable). Arrays are aligned."""
    n_rows = len(dt)
    eid = pd.factorize(ent)[0]
    g = lambda x: pd.Series(x).groupby(eid)  # noqa: E731
    cnt = g(np.zeros(n_rows)).cumcount().to_numpy()

    y = amt - L.amt_mean
    ssum = g(y).cumsum().to_numpy() - y
    ssq = g(y**2).cumsum().to_numpy() - y**2
    prev_max = g(g(amt).cummax().to_numpy()).shift(1).to_numpy()
    first_dt = g(dt).transform("first").to_numpy()
    last_dt = g(dt).shift(1).to_numpy()

    out = {"is_first_seen": cnt == 0, "ent_txn_count": cnt}
    out.update(_derived(cnt, ssum, ssq, amt, L, cfg["amount"]["z_std_floor"]))
    out["ent_max_amt"] = np.where(cnt >= 1, prev_max, 0.0)
    out["ent_age_days"] = np.where(cnt >= 1, (dt - first_dt) / 86400.0, 0.0)
    out["time_since_last_txn"] = np.where(cnt >= 1, dt - last_dt, -1.0)
    out["avg_inter_arrival"] = np.where(
        cnt >= 2, (last_dt - first_dt) / np.maximum(cnt - 1, 1), -1.0
    )

    for col, name in ((dev, "ent_unique_device"), (email, "ent_unique_email")):
        present = col != NA_KEY
        first_seen = ~pd.Series(ent + "\x1f" + col).duplicated().to_numpy() & present
        out[name] = g(first_seen.astype(int)).cumsum().to_numpy() - first_seen
    same_dev = pd.Series(ent + "\x1f" + dev).groupby(pd.factorize(ent + "\x1f" + dev)[0])
    out["device_ent_match"] = np.where(dev != NA_KEY, same_dev.cumcount().to_numpy(), 0)
    card_cnt = pd.Series(np.zeros(n_rows)).groupby(pd.factorize(card)[0]).cumcount().to_numpy()
    out["card_new_addr"] = (cnt == 0) & (card_cnt > 0)

    # windows: one sorted key (entity, time) lets searchsorted stay inside each entity
    order = np.argsort(eid, kind="stable")
    key = eid[order].astype("int64") * BIG + dt[order]
    idx = np.arange(n_rows)
    cum_amt = np.r_[0.0, np.cumsum(amt[order])]
    small = (amt[order] <= L.small_amt_threshold).astype("int64")
    cum_small = np.r_[0, np.cumsum(small)]
    inverse = np.empty(n_rows, dtype="int64")
    inverse[order] = idx
    small_name = small_streak_name(cfg)  # raises if the window is not a velocity window
    small_window = cfg["small_amount"]["window"]
    for name, seconds in cfg["windows"].items():
        lo = np.searchsorted(key, key - seconds, side="left")
        out[f"ent_cnt_{name}"] = (idx - lo)[inverse]
        out[f"ent_sum_{name}"] = (cum_amt[idx] - cum_amt[lo])[inverse]
        if name == small_window:
            out[small_name] = (cum_small[idx] - cum_small[lo])[inverse]
    return pd.DataFrame(out)[history_columns(cfg)]


@dataclass
class EntityState:
    """Running state of one entity (card1 + addr1 proxy = approximate card group)."""

    count: int = 0
    ssum: float = 0.0  # sum of (amount - amt_mean)
    ssq: float = 0.0
    max_amt: float = 0.0
    first_dt: int = 0
    last_dt: int = 0
    devices: dict[str, int] = field(default_factory=dict)
    emails: set[str] = field(default_factory=set)
    events: deque = field(default_factory=deque)  # (dt, amt) of the last max-window seconds


class EntityStore:
    """Entity history for the online path; saved as artifacts/entity_profiles.parquet."""

    def __init__(self, L: LearnedStats, cfg: dict) -> None:
        self.L, self.cfg = L, cfg
        self.entities: dict[str, EntityState] = {}
        self.cards: dict[str, int] = {}
        self.max_window = max(cfg["windows"].values())

    def features(
        self, ent: str, card: str, dev: str, email: str, dt: int, amt: float
    ) -> dict[str, float]:
        """History features of a transaction computed from the state BEFORE it (no update)."""
        L, cfg = self.L, self.cfg
        small_name = small_streak_name(cfg)
        small_window = cfg["small_amount"]["window"]
        st = self.entities.get(ent, EntityState())
        n = st.count
        arr = lambda v: np.array([v], dtype="float64")  # noqa: E731
        out: dict = {"is_first_seen": n == 0, "ent_txn_count": n}
        d = _derived(arr(n), arr(st.ssum), arr(st.ssq), arr(amt), L, cfg["amount"]["z_std_floor"])
        out.update({k: float(v[0]) for k, v in d.items()})
        out["ent_max_amt"] = st.max_amt if n >= 1 else 0.0
        out["ent_age_days"] = (dt - st.first_dt) / 86400.0 if n >= 1 else 0.0
        out["time_since_last_txn"] = float(dt - st.last_dt) if n >= 1 else -1.0
        out["avg_inter_arrival"] = (st.last_dt - st.first_dt) / (n - 1) if n >= 2 else -1.0
        out["ent_unique_device"] = len(st.devices)
        out["ent_unique_email"] = len(st.emails)
        out["device_ent_match"] = st.devices.get(dev, 0) if dev != NA_KEY else 0
        out["card_new_addr"] = n == 0 and self.cards.get(card, 0) > 0
        for name, seconds in cfg["windows"].items():
            ev = [(t, a) for t, a in st.events if t >= dt - seconds]
            out[f"ent_cnt_{name}"] = len(ev)
            out[f"ent_sum_{name}"] = float(sum(a for _, a in ev))
            if name == small_window:
                out[small_name] = sum(1 for _, a in ev if a <= L.small_amt_threshold)
        return {k: out[k] for k in history_columns(cfg)}

    def update(self, ent: str, card: str, dev: str, email: str, dt: int, amt: float) -> None:
        """Add a transaction to the history (call AFTER computing its features)."""
        st = self.entities.setdefault(ent, EntityState())
        y = amt - self.L.amt_mean
        if st.count == 0:
            st.first_dt, st.max_amt = dt, amt
        st.count += 1
        st.ssum += y
        st.ssq += y * y
        st.max_amt = max(st.max_amt, amt)
        st.last_dt = dt
        if dev != NA_KEY:
            st.devices[dev] = st.devices.get(dev, 0) + 1
        if email != NA_KEY:
            st.emails.add(email)
        st.events.append((dt, amt))
        while st.events and st.events[0][0] < dt - self.max_window:
            st.events.popleft()
        self.cards[card] = self.cards.get(card, 0) + 1

    def to_frame(self) -> pd.DataFrame:
        """One row per entity (level='entity') plus one per card1 (level='card')."""
        rows = [
            {
                "level": "entity",
                "key": k,
                "count": s.count,
                "sum_shifted": s.ssum,
                "sumsq_shifted": s.ssq,
                "max_amt": s.max_amt,
                "first_dt": s.first_dt,
                "last_dt": s.last_dt,
                "devices_json": json.dumps(s.devices),
                "emails_json": json.dumps(sorted(s.emails)),
                "events_json": json.dumps(list(s.events)),
            }
            for k, s in self.entities.items()
        ]
        rows += [{"level": "card", "key": k, "count": c} for k, c in self.cards.items()]
        return pd.DataFrame(rows)

    @classmethod
    def from_frame(cls, frame: pd.DataFrame, L: LearnedStats, cfg: dict) -> EntityStore:
        """Rebuild a store saved with to_frame."""
        store = cls(L, cfg)
        for r in frame.itertuples(index=False):
            if r.level == "card":
                store.cards[r.key] = int(r.count)
                continue
            store.entities[r.key] = EntityState(
                count=int(r.count),
                ssum=float(r.sum_shifted),
                ssq=float(r.sumsq_shifted),
                max_amt=float(r.max_amt),
                first_dt=int(r.first_dt),
                last_dt=int(r.last_dt),
                devices=json.loads(r.devices_json),
                emails=set(json.loads(r.emails_json)),
                events=deque((int(t), float(a)) for t, a in json.loads(r.events_json)),
            )
        return store
