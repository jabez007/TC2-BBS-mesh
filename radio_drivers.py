import logging
import abc

logger = logging.getLogger(__name__)


class BaseRadioDriver(abc.ABC):
    """
    Abstract base class for all radio interfaces (Meshtastic, Mesh Core, etc.)
    """

    @abc.abstractmethod
    def send_text(self, text, destination_id, want_ack=True):
        raise NotImplementedError

    @abc.abstractmethod
    def get_nodes(self):
        """Returns a dictionary of nodes keyed by node_id"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_node_by_num(self, node_num):
        """Returns a node object based on its numeric ID"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_my_node_id(self):
        """Returns the ID of the local radio node"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_my_node_num(self):
        """Returns the numeric ID of the local radio node"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_short_name(self, node_id):
        """Returns the short name of a node"""
        raise NotImplementedError

    @abc.abstractmethod
    def close(self):
        """Closes the radio interface"""
        raise NotImplementedError

    @abc.abstractmethod
    def getNode(self, node_id):
        """Returns node info for keepalive"""
        raise NotImplementedError


class MeshtasticDriver(BaseRadioDriver):
    """
    Adapter for the Meshtastic Python library
    """

    def __init__(self, interface):
        self.interface = interface
        # For compatibility with existing code that looks for .bbs_nodes on the interface
        self.bbs_nodes = getattr(interface, "bbs_nodes", [])
        self.allowed_nodes = getattr(interface, "allowed_nodes", [])

    @property
    def myInfo(self):
        # Compatibility for server.py watchdog
        return self.interface.myInfo

    @property
    def nodes(self):
        # Compatibility for existing code accessing .nodes directly
        return self.interface.nodes

    def send_text(self, text, destination_id, want_ack=True):
        return self.interface.sendText(
            text=text,
            destinationId=destination_id,
            wantAck=want_ack,
            wantResponse=False,
        )

    def get_nodes(self):
        return self.interface.nodes

    def get_node_by_num(self, node_num):
        for _, node in self.interface.nodes.items():
            if node["num"] == node_num:
                return node
        return None

    def get_my_node_id(self):
        return self.interface.myInfo.my_node_id

    def get_my_node_num(self):
        return self.interface.myInfo.my_node_num

    def get_short_name(self, node_id):
        node_info = self.interface.nodes.get(node_id)
        if node_info:
            return node_info["user"].get("shortName")
        return None

    def getNode(self, node_id):
        # Compatibility for keepalive
        return self.interface.getNode(node_id)

    def close(self):
        return self.interface.close()


class MeshCoreStubDriver(BaseRadioDriver):
    """
    Stub for the future Mesh Core integration
    """

    def __init__(self, config):
        self.config = config
        logger.info("Mesh Core Driver Stub initialized (Hardware not yet connected)")

    def send_text(self, text, destination_id, want_ack=True):
        logger.info(f"MESH CORE STUB: Sending '{text}' to {destination_id}")
        return True

    def get_nodes(self):
        return {}

    def get_node_by_num(self, node_num):
        return None

    def get_my_node_id(self):
        return "MC-STUB"

    def get_my_node_num(self):
        return 0

    def get_short_name(self, node_id):
        return "Stub"

    def close(self):
        pass

    def getNode(self, node_id):
        return None
