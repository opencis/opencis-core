"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.cci.fabric_manager.gae.identify_gae import (
    IdentifyGaeCommand,
    IdentifyGaeResponsePayload,
    VppbGlobalMemorySupportInfo,
)
from opencis.cxl.cci.fabric_manager.gae.get_pid_access_vectors import (
    GetPidAccessVectorsCommand,
    GetPidAccessVectorsRequestPayload,
    GetPidAccessVectorsResponsePayload,
)
from opencis.cxl.cci.fabric_manager.gae.proxy_gfd_mgmt import (
    ProxyGfdMgmtCommand,
    ProxyGfdMgmtRequestPayload,
    ProxyGfdMgmtResponsePayload,
)
from opencis.cxl.cci.fabric_manager.gae.get_proxy_thread_status import (
    GetProxyThreadStatusCommand,
    GetProxyThreadStatusRequestPayload,
    GetProxyThreadStatusResponsePayload,
)
from opencis.cxl.cci.fabric_manager.gae.cancel_proxy_thread import (
    CancelProxyThreadCommand,
    CancelProxyThreadRequestPayload,
)
from opencis.cxl.cci.fabric_manager.gae.fabric_crawl_out import (
    FabricCrawlOutCommand,
    FabricCrawlOutRequestPayload,
    FabricCrawlOutResponsePayload,
    EmbeddedCciCommand,
    EmbeddedCciResponse,
    DspTunnelRegistry,
)

__all__ = [
    # Identify GAE (5800h)
    "IdentifyGaeCommand",
    "IdentifyGaeResponsePayload",
    "VppbGlobalMemorySupportInfo",
    # Get PID Access Vectors (5802h)
    "GetPidAccessVectorsCommand",
    "GetPidAccessVectorsRequestPayload",
    "GetPidAccessVectorsResponsePayload",
    # Proxy GFD Management Command (5809h)
    "ProxyGfdMgmtCommand",
    "ProxyGfdMgmtRequestPayload",
    "ProxyGfdMgmtResponsePayload",
    # Get Proxy Thread Status (580Ah)
    "GetProxyThreadStatusCommand",
    "GetProxyThreadStatusRequestPayload",
    "GetProxyThreadStatusResponsePayload",
    # Cancel Proxy Thread (580Bh)
    "CancelProxyThreadCommand",
    "CancelProxyThreadRequestPayload",
    # Fabric Crawl Out (5701h)
    "FabricCrawlOutCommand",
    "FabricCrawlOutRequestPayload",
    "FabricCrawlOutResponsePayload",
    "EmbeddedCciCommand",
    "EmbeddedCciResponse",
    "DspTunnelRegistry",
]
