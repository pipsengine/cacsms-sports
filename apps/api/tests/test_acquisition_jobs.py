import pytest
from app.modules.acquisition.jobs import validate_feed_url,configured_feed,enqueue

def test_feed_url_blocks_private_and_unsafe():
 for url in ['http://example.com/feed','https://localhost/feed','https://127.0.0.1/feed','https://user:pass@example.com/feed','https://example.com:8443/feed','https://example.internal/feed']:
  with pytest.raises(ValueError):validate_feed_url(url,resolve=False)

def test_feed_url_allows_https_public_syntax():
 assert validate_feed_url('https://data.example.org/fixtures.json',resolve=False).startswith('https://')

def test_unconfigured_feed_fails_closed(monkeypatch):
 monkeypatch.setenv('SPORTS_SOURCE_FEEDS_JSON','{}')
 with pytest.raises(ValueError):configured_feed('provider-id','standings')

def test_no_source_not_enqueued():
 class Session:
  def get(self,model,id):return None
 with pytest.raises(PermissionError):enqueue(Session(),'missing','fixture','standings','2026-11-14')
