import time
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.api_core.exceptions import AlreadyExists


class Store:
    def __init__(self, project):
        self.db = firestore.Client(project=project)

    def ref(self, collection, key):
        return self.db.collection(collection).document(key)

    def get(self, collection, key):
        return self.ref(collection, key).get().to_dict()

    def put(self, collection, key, value):
        self.ref(collection, key).set(value)

    def create(self, collection, key, value):
        try:
            self.ref(collection, key).create(value)
            return True
        except AlreadyExists:
            return False

    def delete(self, collection, key):
        self.ref(collection, key).delete()

    def list(self, collection, field, value, limit=100):
        return [d.to_dict() for d in self.db.collection(collection)
                .where(filter=FieldFilter(field, "==", value)).limit(limit).stream()]

    def consume_pair(self, key):
        ref = self.ref("pairings", key)

        @firestore.transactional
        def consume(tx):
            data = ref.get(transaction=tx).to_dict()
            if not data or data["expires"] < time.time():
                return None
            tx.delete(ref)
            return data

        return consume(self.db.transaction())

    def messages(self, uid, device_id, after):
        query = (self.db.collection("messages")
                 .where(filter=FieldFilter("deviceId", "==", device_id))
                 .order_by("cursor").limit(100))
        if after:
            query = query.start_after({"cursor": after})
        return [d.to_dict() for d in query.stream() if d.to_dict()["owner"] == uid]

    def trip_events(self, trip_id):
        return [d.to_dict() for d in self.db.collection("events")
                .where(filter=FieldFilter("tripId", "==", trip_id))
                .order_by("payload.at").limit(1000).stream()]

    def limit(self, key, maximum, seconds=60):
        # A fixed time bucket, shared across all Cloud Run instances.
        bucket = int(time.time()) // seconds
        ref = self.ref("limits", f"{key}-{bucket}")

        @firestore.transactional
        def increment(tx):
            data = ref.get(transaction=tx).to_dict() or {"count": 0}
            if data["count"] >= maximum:
                return False
            from datetime import datetime, timezone
            tx.set(ref, {"count": data["count"] + 1,
                         "expireAt": datetime.fromtimestamp((bucket + 2) * seconds, timezone.utc)})
            return True

        return increment(self.db.transaction())
