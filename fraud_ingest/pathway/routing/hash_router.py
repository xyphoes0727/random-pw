import hashlib
import logging

logger = logging.getLogger(__name__)


def get_instance_for_account(account_id: str, num_instances: int = 3) -> int:
    """
    Maps an `account_id` to a processing instance index (0 to num_instances-1)
    using consistent hashing (MD5 modulo).

    Ensures the same account always maps to the same worker for stateful
    processing.
    """
    hash_val = int(hashlib.md5(account_id.encode()).hexdigest(), 16)
    instance = hash_val % num_instances
    return instance


def should_process_transaction(user_id: str, instance_id: int,
                               num_instances: int = 3) -> bool:
    """
    Checks if the transaction, identified by `user_id`, should be processed
    by the current local `instance_id` using consistent hashing.
    """
    return get_instance_for_account(user_id, num_instances) == instance_id
