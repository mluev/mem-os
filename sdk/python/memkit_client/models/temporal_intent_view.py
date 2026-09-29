from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.temporal_intent_view_order_type_0 import TemporalIntentViewOrderType0

if TYPE_CHECKING:
    from ..models.temporal_window import TemporalWindow


T = TypeVar("T", bound="TemporalIntentView")


@_attrs_define
class TemporalIntentView:
    """
    Attributes:
        asks_time (bool):
        order (None | TemporalIntentViewOrderType0):
        window (None | TemporalWindow):
    """

    asks_time: bool
    order: None | TemporalIntentViewOrderType0
    window: None | TemporalWindow
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.temporal_window import TemporalWindow

        asks_time = self.asks_time

        order: None | str
        if isinstance(self.order, TemporalIntentViewOrderType0):
            order = self.order.value
        else:
            order = self.order

        window: dict[str, Any] | None
        if isinstance(self.window, TemporalWindow):
            window = self.window.to_dict()
        else:
            window = self.window

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "asks_time": asks_time,
                "order": order,
                "window": window,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.temporal_window import TemporalWindow

        d = dict(src_dict)
        asks_time = d.pop("asks_time")

        def _parse_order(data: object) -> None | TemporalIntentViewOrderType0:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                order_type_0 = TemporalIntentViewOrderType0(data)

                return order_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TemporalIntentViewOrderType0, data)

        order = _parse_order(d.pop("order"))

        def _parse_window(data: object) -> None | TemporalWindow:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                window_type_0 = TemporalWindow.from_dict(data)

                return window_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TemporalWindow, data)

        window = _parse_window(d.pop("window"))

        temporal_intent_view = cls(
            asks_time=asks_time,
            order=order,
            window=window,
        )

        temporal_intent_view.additional_properties = d
        return temporal_intent_view

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()
