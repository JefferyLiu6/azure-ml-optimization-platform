from __future__ import annotations

import json
from abc import ABC, abstractmethod
from contextlib import suppress
from pathlib import Path
from typing import Any


class ArtifactStore(ABC):
    @abstractmethod
    def put_json(self, experiment_id: str, name: str, value: Any) -> str: ...

    @abstractmethod
    def put_bytes(self, experiment_id: str, name: str, value: bytes) -> str: ...

    @abstractmethod
    def health(self) -> None: ...


class LocalArtifactStore(ArtifactStore):
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_json(self, experiment_id: str, name: str, value: Any) -> str:
        return self.put_bytes(
            experiment_id,
            name,
            json.dumps(value, indent=2, default=str, allow_nan=False).encode(),
        )

    def put_bytes(self, experiment_id: str, name: str, value: bytes) -> str:
        destination = self.root / experiment_id / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(value)
        return str(destination.resolve())

    def health(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


class AzureBlobArtifactStore(ArtifactStore):
    def __init__(self, container_client: Any):
        from azure.core.exceptions import ResourceExistsError

        self.container = container_client
        with suppress(ResourceExistsError):
            self.container.create_container()

    def put_json(self, experiment_id: str, name: str, value: Any) -> str:
        return self.put_bytes(
            experiment_id,
            name,
            json.dumps(value, indent=2, default=str, allow_nan=False).encode(),
        )

    def put_bytes(self, experiment_id: str, name: str, value: bytes) -> str:
        blob_name = f"experiments/{experiment_id}/{name}"
        client = self.container.get_blob_client(blob_name)
        client.upload_blob(value, overwrite=True)
        return str(client.url)

    def health(self) -> None:
        next(iter(self.container.list_blobs(results_per_page=1).by_page()), None)


def convergence_svg(
    points: list[tuple[float, float]], width: int = 800, height: int = 420
) -> bytes:
    """Create a dependency-free convergence plot artifact."""
    if not points:
        return b""
    padding = 50
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    xspan = xmax - xmin or 1.0
    yspan = ymax - ymin or 1.0
    coords = []
    for x, y in points:
        px = padding + (x - xmin) / xspan * (width - 2 * padding)
        py = height - padding - (y - ymin) / yspan * (height - 2 * padding)
        coords.append(f"{px:.2f},{py:.2f}")
    content = "".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" ',
            f'viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            f'<line x1="{padding}" y1="{height - padding}" x2="{width - padding}" ',
            f'y2="{height - padding}" stroke="#64748b"/>',
            f'<line x1="{padding}" y1="{padding}" x2="{padding}" ',
            f'y2="{height - padding}" stroke="#64748b"/>',
            '<polyline fill="none" stroke="#2563eb" stroke-width="3" ',
            f'points="{" ".join(coords)}"/>',
            f'<text x="{width / 2}" y="{height - 10}" text-anchor="middle" ',
            'font-family="sans-serif" font-size="14">Cumulative cost</text>',
            f'<text x="18" y="{height / 2}" text-anchor="middle" ',
            f'transform="rotate(-90 18 {height / 2})" font-family="sans-serif" ',
            'font-size="14">Best objective</text></svg>',
        ]
    )
    return content.encode()
