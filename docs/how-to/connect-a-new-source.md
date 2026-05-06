# Connect a new source

Connectors pull documents from external systems (APIs, message queues, cloud storage) into the ingestion pipeline. riverbank ships a filesystem connector; you can add others via entry points.

## The base class

```python
from riverbank.connectors.base import BaseConnector, SourceDocument

class MyConnector(BaseConnector):
    name = "my-connector"

    def discover(self, config: dict) -> list[SourceDocument]:
        """Return a list of documents available from the source."""
        # Query your API / bucket / queue
        documents = []
        for item in self._fetch_items(config):
            documents.append(SourceDocument(
                iri=f"http://example.org/source/{item['id']}",
                content=item["body"],
                metadata=item.get("metadata", {}),
            ))
        return documents
```

## Register via entry point

```toml
[project.entry-points."riverbank.connectors"]
my-connector = "my_package.connectors:MyConnector"
```

## Configuration

Connectors receive their configuration from the profile or environment variables. Common patterns:

```yaml
# In the compiler profile
connector: my-connector
connector_config:
  api_url: "https://api.example.com/docs"
  api_key: "${MY_API_KEY}"
```

## Test your connector

```python
def test_my_connector():
    from my_package.connectors import MyConnector

    connector = MyConnector()
    docs = connector.discover({"api_url": "http://mock/", "api_key": "test"})
    assert len(docs) > 0
    assert all(d.iri for d in docs)
```
