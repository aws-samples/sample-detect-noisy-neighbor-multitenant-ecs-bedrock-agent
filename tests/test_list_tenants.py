from agent.tools.list_tenants import list_tenants


def test_returns_tenants_for_cluster(registry: str, cluster_name: str) -> None:
    result = list_tenants(cluster_name=cluster_name)  # type: ignore[call-arg]
    ids = sorted(t["tenant_id"] for t in result["tenants"])
    assert ids == ["tenant-a", "tenant-b"]
    assert all(t["cluster_name"] == cluster_name for t in result["tenants"])


def test_unknown_cluster_returns_empty(registry: str) -> None:
    result = list_tenants(cluster_name="not-a-real-cluster")  # type: ignore[call-arg]
    assert result["tenants"] == []
