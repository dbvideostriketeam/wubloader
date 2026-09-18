
from urllib.parse import urlparse

from common.requests import InstrumentedSession

from . import phoenix


class Client:
	def __init__(self, event_id=None, base_url="https://desertbus.org/api"):
		self.session = InstrumentedSession()
		self.base_url = base_url
		self.event_id = event_id or self.default_event_id()

	def _get(self, name, url):
		resp = self.session.get(url, metric_name=name)
		resp.raise_for_status()
		return resp.json()

	def _event_get(self, name, path):
		return self._get(name, "/".join([self.base_url, "events", self.event_id, path]))

	def _event_paged(self, name, path, item_key):
		data = self._event_get(name, path)
		while data[item_key]:
			yield from data[item_key]
			url = data["next_page"]
			if url is None:
				break
			data = self._get(name, url)

	def events(self):
		return self._get("list_events", "/".join([self.base_url, "events"]))["events"]

	def default_event_id(self):
		return self.events()[0]["id"]

	def event(self, id=None):
		if id is None:
			id = self.event_id
		matches = [e for e in self.events() if e["id"] == id]
		if not matches:
			raise ValueError(f"No such event {id!r}")
		return matches[0]

	def blog_posts(self):
		return self._event_paged("list_posts", "blog", "posts")

	def donations(self):
		return self._event_paged("list_donations", "donations", "donations")

	def guests(self):
		return self._event_get("list_guests", "guests")["guests"]

	def prizes(self):
		return self._event_get("list_prizes", "prizes")["prizes"]

	def prize(self, id):
		return self._event_get("get_prize", f"prizes/{id}")["prize"]

	def event_stream(self):
		url = urlparse(self.base_url)
		url = url._replace(scheme={
			"http": "ws",
			"https": "wss",
		}[url.scheme])
		return EventStream(url.geturl(), self.event_id)


class EventStream:
	def __init__(self, base_url, event_id):
		self.phoenix = phoenix.Client("/".join([base_url, "socket/websocket?vsn=2.0.0"]))
		self.event_id = event_id

	def subscribe_live_auction(self):
		self.phoenix.subscribe(f"auctions:{self.event_id}")

	def subscribe_blog(self):
		self.phoenix.subscribe(f"blog:{self.event_id}")

	def subscribe_donations(self, last_seen=None):
		params = {} if last_seen is None else {"last_seen": last_seen}
		self.phoenix.subscribe(f"donations:{self.event_id}", params)

	def subscribe_prizes(self):
		self.phoenix.subscribe(f"prizes:{self.event_id}")

	def subscribe_total(self):
		self.phoenix.subscribe(f"total:{self.event_id}")

	def recv(self):
		for message in self.phoenix.recv():
			# filter out heartbeats
			if message.topic != "phoenix":
				yield message


if __name__ == '__main__':
	import json

	import argh

	@argh.dispatch_command
	@argh.arg("endpoint", choices=["events", "blog_posts", "donations", "guests", "prizes"])
	def main(endpoint, base_url="https://desertbus.org/api", event_id=None):
		client = Client(event_id=event_id, base_url=base_url)
		data = getattr(client, endpoint)()
		for item in data:
			print(json.dumps(item, indent=4))
