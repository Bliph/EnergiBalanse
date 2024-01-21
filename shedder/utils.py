import datetime

###########################################################
#
#
def ts2iso(ts):
    local_zone = datetime.datetime.now().astimezone().tzinfo
    ts_iso = datetime.datetime.fromtimestamp(ts, local_zone).isoformat()
    return ts_iso

