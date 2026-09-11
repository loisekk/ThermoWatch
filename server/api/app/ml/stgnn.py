"""Spatio-temporal GNN (PyG): GCN spatial message-passing + LSTM temporal core.
Optional dependency — server runs ensemble/heuristic when torch/PyG absent."""
from __future__ import annotations

import importlib.util
from typing import Any

from app.ml.features import FEATURE_ORDER

# Probe availability without importing: no partial bindings, no ImportError juggling,
# and the guarded block below gives type checkers the real (non-optional) types.
AVAILABLE = (
    importlib.util.find_spec("torch") is not None
    and importlib.util.find_spec("torch_geometric") is not None
)

if AVAILABLE:
    import torch  # type: ignore
    from torch import nn  # type: ignore
    from torch_geometric.nn import GCNConv  # type: ignore

    class FireSTGNN(nn.Module):  # pyright: ignore[reportRedeclaration]
        """x: [T, N, F] day-snapshots; edge_index: H3 neighbour graph."""

        def __init__(self, in_dim: int = len(FEATURE_ORDER), hidden: int = 64, out_dim: int = 10) -> None:
            super().__init__()
            self.conv1 = GCNConv(in_dim, hidden)
            self.conv2 = GCNConv(hidden, hidden)
            self.lstm = nn.LSTM(hidden, hidden, batch_first=True)
            self.head = nn.Linear(hidden, out_dim)

        def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
            t, n, f = x.shape
            h = torch.relu(self.conv2(self.conv1(x.reshape(t * n, f), edge_index), edge_index))
            out, _ = self.lstm(h.reshape(t, n, -1))
            return torch.softmax(self.head(out[:, -1]), dim=-1)
else:
    class FireSTGNN:
        """Stub raising a clear error if instantiated without torch/PyG.

        Mirrors the real class's inference surface (load_state_dict/eval/__call__)
        so type checkers see one consistent interface regardless of whether the
        optional dependency is installed.
        """

        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("torch/torch-geometric not installed")

        def load_state_dict(self, state_dict: object, **kwargs: object) -> None:
            raise RuntimeError("torch/torch-geometric not installed")

        def eval(self) -> FireSTGNN:
            raise RuntimeError("torch/torch-geometric not installed")

        def __call__(self, *args: object, **kwargs: object) -> Any:
            raise RuntimeError("torch/torch-geometric not installed")

MODEL_NAME = "stgnn-v0" if AVAILABLE else "heuristic-ensemble-v0"



