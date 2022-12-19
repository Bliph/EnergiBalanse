from integration.rest_client import RESTClient

###############################################################################
# Wrapper class with XML <-> Dict conversion
# Includes XML upload as form data
#
class TeslaClient(RESTClient):
    def __init__(self, host, port, protocol, logger, timeouts):
        HTTPClient.__init__(self, host, port, protocol, logger, timeouts)
