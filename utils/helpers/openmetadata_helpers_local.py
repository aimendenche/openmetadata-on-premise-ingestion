import os
from typing import Dict

from utils.helpers.openmetadata_helpers import (
    OpenMetadataQualityFramework,
    load_omd_config_from_airflow,
)


def load_omd_config_from_airflow_local() -> Dict[str, str]:
    """
    Prefer Airflow Variables. Fallback to local defaults for localhost testing.
    """
    try:
        return load_omd_config_from_airflow()
    except RuntimeError:
        omd_api_url = os.getenv("OMD_API_V1_URL", "http://localhost:8585/api/v1")
        omd_url = os.getenv("OMD_URL", "http://localhost:8585")
        jwt_token = (
            os.getenv("Quality_token")
            or os.getenv("QUALITY_TOKEN")
            or os.getenv("OMD_JWT_TOKEN")
            or ""
        )
        if not jwt_token:
            raise RuntimeError(
                "Missing OpenMetadata token. Set Airflow Variable 'Quality_token' "
                "or env QUALITY_TOKEN."
            )
        return {
            "OMD_API_URL": omd_api_url,
            "OMD_URL": omd_url,
            "JWT_TOKEN": jwt_token,
        }


class OpenMetadataQualityFrameworkLocal(OpenMetadataQualityFramework):
    """
    Local testing wrapper with localhost fallbacks.
    """

    @classmethod
    def from_airflow_variables(cls, comment_user: str = "dataquality_bot") -> "OpenMetadataQualityFrameworkLocal":
        config = load_omd_config_from_airflow_local()
        return cls(
            omd_api_url=config["OMD_API_URL"],
            omd_url=config["OMD_URL"],
            jwt_token=config["JWT_TOKEN"],
            comment_user=comment_user,
        )
