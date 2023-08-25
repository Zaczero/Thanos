from datetime import datetime


def xmltodict_postprocessor(path, key, value):
    if key in ('@id', '@ref', '@changeset', '@uid', '@num_changes', '@comments_count'):
        return key, int(value)

    if key in ('@version', '@min_lat', '@max_lat', '@min_lon', '@max_lon'):
        try:
            return key, int(value)
        except ValueError:
            return key, float(value)

    if key in ('@created_at', '@closed_at'):
        return key, datetime.fromisoformat(value)

    if key in ('@open', '@visible'):
        return key, value == 'true'

    return key, value
