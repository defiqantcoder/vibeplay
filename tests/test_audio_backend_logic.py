from vibeplay.hardware import AudioEndpointInfo, discover_audio_endpoints, get_active_or_best_dac


def test_audio_endpoints_discovery(mocker):
    mocker.patch("vibeplay.hardware.Path.read_text", return_value="mock card")
    mocker.patch("vibeplay.hardware.Path.exists", return_value=True)
    mocker.patch("vibeplay.hardware.Path.is_dir", return_value=True)
    mocker.patch("vibeplay.hardware.Path.iterdir", return_value=[])
    endpoints = discover_audio_endpoints()
    assert isinstance(endpoints, list)


def test_get_active_or_best_dac_no_dacs():
    endpoints = [
        AudioEndpointInfo(card_index=0, card_id="Intel", card_name="HDA Intel PCH", driver="HDA-Intel", is_usb_dac=False),
        AudioEndpointInfo(card_index=1, card_id="NVidia", card_name="HDA NVidia", driver="HDA-Intel", is_usb_dac=False),
    ]
    dac = get_active_or_best_dac(endpoints=endpoints)
    assert dac is None


def test_get_active_or_best_dac_multiple_standard_dacs():
    endpoints = [
        AudioEndpointInfo(card_index=0, card_id="Intel", card_name="HDA Intel PCH", driver="HDA-Intel", is_usb_dac=False),
        AudioEndpointInfo(card_index=1, card_id="GenericUSB", card_name="Generic USB Audio", driver="usb-audio", is_usb_dac=True),
        AudioEndpointInfo(card_index=2, card_id="AnotherUSB", card_name="Another USB Audio", driver="usb-audio", is_usb_dac=True),
    ]
    dac = get_active_or_best_dac(endpoints=endpoints)
    assert dac is not None
    assert dac.card_name == "Generic USB Audio"


def test_get_active_or_best_dac_high_end_dac_priority():
    endpoints = [
        AudioEndpointInfo(card_index=0, card_id="Intel", card_name="HDA Intel PCH", driver="HDA-Intel", is_usb_dac=False),
        AudioEndpointInfo(card_index=1, card_id="GenericUSB", card_name="Generic USB Audio", driver="usb-audio", is_usb_dac=True),
        AudioEndpointInfo(card_index=2, card_id="FiiO", card_name="FiiO KA15", driver="usb-audio", is_usb_dac=True),
    ]
    dac = get_active_or_best_dac(endpoints=endpoints)
    assert dac is not None
    assert dac.card_name == "FiiO KA15"


def test_get_active_or_best_dac_fallback_to_discovery(mocker):
    mock_endpoints = [
        AudioEndpointInfo(card_index=0, card_id="Intel", card_name="HDA Intel PCH", driver="HDA-Intel", is_usb_dac=False),
        AudioEndpointInfo(card_index=1, card_id="Topping", card_name="Topping D90", driver="usb-audio", is_usb_dac=True),
    ]
    mocker.patch("vibeplay.hardware.discover_audio_endpoints", return_value=mock_endpoints)
    dac = get_active_or_best_dac(endpoints=None)
    assert dac is not None
    assert dac.card_name == "Topping D90"
