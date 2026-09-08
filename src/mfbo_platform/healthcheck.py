from mfbo_platform.config import get_settings
from mfbo_platform.factory import (
    artifacts_from_settings,
    engine_from_settings,
    repository_from_settings,
)


def main() -> None:
    settings = get_settings()
    repository_from_settings(settings).health()
    artifacts_from_settings(settings).health()
    engine_from_settings(settings).health()


if __name__ == "__main__":
    main()
