"""Privacy-preserving tracking response projection; not order reconciliation.

The live Uzbekistan endpoint has returned an empty top-level array. The contents
of a nonempty array have not been captured, so array entries are never decoded or
assumed to correspond one-to-one to orders.
"""


class TrackingShapeError(ValueError):
    """The response is not the observed top-level array shape."""


def project_tracking_response(data):
    """Return structural information only; never expose unknown entry contents."""
    if not isinstance(data, list):
        raise TrackingShapeError('Unrecognized active-order response; no conclusion possible')
    if not data:
        return {
            'active_order_count': 0,
            'history_complete': False,
            'reconciles_uncertain_submission': False,
        }
    return {
        'active_order_count': None,
        'feed_entry_count': len(data),
        'history_complete': False,
        'reconciles_uncertain_submission': False,
        'note': ('Nonempty tracking entries have an unverified schema; their count '
                 'is not a verified order count. Check the official app for status.'),
    }
