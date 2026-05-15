"""Test DirectorService helper methods."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.director import DirectorService


class TestDirectorServiceExtractors:
    def test_extract_dimension_config(self):
        """Should extract key-value pairs from DimensionServerGroupConfig."""
        config = {
            "MapName": "DeepDesert",
            "DimensionServerGroupConfig": {
                "playerHardCap": 50,
                "minServers": 2,
                "numExtraServers": 1,
                "enableAutomaticInstanceScaling": True,
                "instanceScalingThrottlingSeconds": 300,
            }
        }
        kv = DirectorService.extract_server_config_kv(config)
        assert kv["PlayerHardCap"] == 50
        assert kv["MinServers"] == 2
        assert kv["NumExtraServers"] == 1
        assert kv["EnableAutomaticInstanceScaling"] == "True"
        assert kv["InstanceScalingThrottlingSeconds"] == 300

    def test_extract_classical_config(self):
        """Should extract key-value pairs from ClassicalInstancingGroupConfig."""
        config = {
            "MapName": "HaggaBasin",
            "ClassicalInstancingGroupConfig": {
                "playerHardCap": 30,
                "minServers": 1,
            }
        }
        kv = DirectorService.extract_server_config_kv(config)
        assert kv["PlayerHardCap"] == 30
        assert kv["MinServers"] == 1

    def test_extract_single_server_config(self):
        """Should extract key-value pairs from SingleServerConfig."""
        config = {
            "MapName": "TestMap",
            "SingleServerConfig": {
                "playerHardCap": 100,
            }
        }
        kv = DirectorService.extract_server_config_kv(config)
        assert kv["PlayerHardCap"] == 100

    def test_extract_empty_config(self):
        """Should return empty dict for unknown config format."""
        config = {"MapName": "TestMap", "UnknownConfig": {}}
        kv = DirectorService.extract_server_config_kv(config)
        assert kv == {}

    def test_extract_character_transfer_kv(self):
        """Should extract character transfer key-value pairs."""
        config = {
            "ForceIsWorldClosed": True,
            "ForceIsWorldClosingSoon": False,
        }
        kv = DirectorService.extract_character_transfer_kv(config)
        assert kv["ForceIsWorldClosed"] == "True"
        assert kv["ForceIsWorldClosingSoon"] == "False"

    def test_extract_character_transfer_empty(self):
        """Should return empty dict when no transfer keys present."""
        config = {"SomeOtherKey": "value"}
        kv = DirectorService.extract_character_transfer_kv(config)
        assert kv == {}
