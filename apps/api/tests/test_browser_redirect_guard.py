"""Browser capture must police every redirect hop (Playwright does not route redirect hops itself)."""
import asyncio,functools,socket
import pytest
from app.modules.vision import browser,security

PUBLIC={'source.example':'93.184.215.14','cdn.example':'93.184.215.15','www.betexplorer.com':'188.92.44.58','internal.example':'10.0.0.5'}


def fake_resolver(host,port,type=None):
 return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(PUBLIC.get(host,'93.184.215.99'),port))]


class Response:
 def __init__(self,status,location=None):self.status=status;self.headers={'location':location} if location else {};self.disposed=False
 async def dispose(self):self.disposed=True


class Request:
 def __init__(self,url):self.url=url


class Route:
 def __init__(self,url,response):self.request=Request(url);self._response=response;self.outcome=None;self.fetch_args=None
 async def fetch(self,**kwargs):self.fetch_args=kwargs;return self._response
 async def abort(self,code='failed'):self.outcome=('abort',code)
 async def fulfill(self,response=None):self.outcome=('fulfill',response.status)


@pytest.fixture(autouse=True)
def offline_dns(monkeypatch):
 monkeypatch.setattr(browser,'validate_destination',functools.partial(security.validate_destination,resolver=fake_resolver))


def run(url,response,hosts=('source.example','internal.example')):
 route=Route(url,response);asyncio.run(browser.guard_route(route,list(hosts)));return route


def test_plain_allowed_request_is_fetched_without_following_redirects():
 route=run('https://source.example/table',Response(200))
 assert route.outcome==('fulfill',200) and route.fetch_args=={'max_redirects':0}


def test_redirect_within_allowlist_is_handed_to_browser():
 assert run('https://source.example/a',Response(302,'/b')).outcome==('fulfill',302)


def test_redirect_to_unapproved_host_is_aborted():
 response=Response(302,'https://cdn.example/x')
 route=run('https://source.example/a',response)
 assert route.outcome==('abort','blockedbyclient') and response.disposed


def test_redirect_to_prohibited_source_is_aborted_even_if_allowlisted():
 route=run('https://source.example/a',Response(301,'https://www.betexplorer.com/football/'),hosts=('source.example','www.betexplorer.com'))
 assert route.outcome==('abort','blockedbyclient')


def test_redirect_to_internal_address_is_aborted():
 assert run('https://source.example/a',Response(307,'https://internal.example/admin')).outcome==('abort','blockedbyclient')


def test_redirect_downgrade_to_http_is_aborted():
 assert run('https://source.example/a',Response(302,'http://source.example/a')).outcome==('abort','blockedbyclient')


def test_unapproved_request_is_never_fetched():
 route=run('https://cdn.example/lib.js',Response(200))
 assert route.outcome==('abort','blockedbyclient') and route.fetch_args is None
