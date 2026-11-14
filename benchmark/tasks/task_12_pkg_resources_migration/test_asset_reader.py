from unittest.mock import patch, MagicMock
import asset_reader

def test_read_package_asset_uses_importlib():
    with patch("importlib.resources.files") as mock_files:
        mock_asset = MagicMock()
        mock_asset.read_text.return_value = "asset content"
        mock_files.return_value.joinpath.return_value = mock_asset
        
        content = asset_reader.read_package_asset("my_pkg", "data.txt")
        assert content == "asset content"
