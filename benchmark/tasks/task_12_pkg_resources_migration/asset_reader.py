# Stale: pkg_resources is deprecated
import pkg_resources

def read_package_asset(package_name: str, asset_filename: str) -> str:
    # Stale API
    return pkg_resources.resource_string(package_name, asset_filename).decode("utf-8")
