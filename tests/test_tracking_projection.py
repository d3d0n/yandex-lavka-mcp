import json
import pytest

from lavka_tracking_projection import TrackingShapeError, project_tracking_response


def test_observed_empty_array():
    assert project_tracking_response([]) == {
        'active_order_count': 0,
        'history_complete': False,
        'reconciles_uncertain_submission': False,
    }


@pytest.mark.parametrize('entry', [
    {'orderId': 'private-id', 'status': 'private-status'},
    None, 'private-string', 42, [], {'nested': {'private': 'private-value'}},
])
def test_unverified_entries_are_only_counted_and_never_returned(entry):
    # Synthetic entries test privacy, not the actual nonempty upstream schema.
    result = project_tracking_response([entry, entry])
    assert result['feed_entry_count'] == 2
    assert result['active_order_count'] is None
    assert result['history_complete'] is False
    assert result['reconciles_uncertain_submission'] is False
    assert 'private' not in json.dumps(result)
    assert 'not a verified order count' in result['note']


@pytest.mark.parametrize('data', [{}, {'orders': []}, None, 'secret', 0, False])
def test_other_top_level_shapes_fail_without_leaking_data(data):
    with pytest.raises(TrackingShapeError) as exc:
        project_tracking_response(data)
    assert 'secret' not in str(exc.value)
