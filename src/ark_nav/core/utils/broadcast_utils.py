import ray
import pickle
from ray.serve._private.common import RequestMetadata

from ark_nav.core.utils.nav_logger import get_logger

logger = get_logger("broadcast")


def broadcast(method_name: str, deployment_name: str, namespace: str="serve", app_name: str="default", **kwargs):
    all_actors = ray.util.list_named_actors(all_namespaces=True)
    replica_actors = [
        actor for actor in all_actors
        if actor["namespace"] == namespace
        and actor["name"].startswith(f"SERVE_REPLICA::{app_name}#{deployment_name}")
    ]
    logger.info(f"需要广播的副本列表: {replica_actors}")
    replica_actors = [ray.get_actor(name=actor["name"], namespace=namespace) for actor in replica_actors]
    dummy_rm = pickle.dumps(RequestMetadata(
        request_id="1", internal_request_id="1",
        call_method=method_name
    ))
    results = ray.get([actor.handle_request.remote(pickled_request_metadata=dummy_rm, **kwargs)
                       for actor in replica_actors])
    logger.info(results)
