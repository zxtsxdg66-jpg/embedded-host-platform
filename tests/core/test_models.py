from core.models import ChannelId, ClientId, CommandType, DeviceId


def test_id_aliases_accept_plain_strings() -> None:
    device_id: DeviceId = "device-1"
    client_id: ClientId = "client-1"
    channel_id: ChannelId = "channel-1"
    command_type: CommandType = "READ_STATUS"

    assert isinstance(device_id, str)
    assert isinstance(client_id, str)
    assert isinstance(channel_id, str)
    assert isinstance(command_type, str)
