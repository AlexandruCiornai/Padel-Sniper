from datetime import datetime, timedelta, timezone

import pytest

from core import TZ, bot_starts_at, is_valid_pin, restore_action, slot_datetime, slot_opens_at


def bucharest(*args):
    return datetime(*args, tzinfo=TZ)


class TestSlotDatetime:
    def test_parses_date_and_hour_on_bucharest_clock(self):
        assert slot_datetime("2026-06-29", "15:00") == bucharest(2026, 6, 29, 15, 0)

    def test_keeps_minutes(self):
        assert slot_datetime("2026-06-29", "07:30") == bucharest(2026, 6, 29, 7, 30)

    @pytest.mark.parametrize("hour", ["15", "24:00", "7:00", "15:60", "15:00:00", "ab:cd", ""])
    def test_rejects_malformed_hour(self, hour):
        with pytest.raises(ValueError):
            slot_datetime("2026-06-29", hour)

    @pytest.mark.parametrize("date", ["29-06-2026", "2026-02-30", "2026/06/29", ""])
    def test_rejects_malformed_date(self, date):
        with pytest.raises(ValueError):
            slot_datetime(date, "15:00")


class TestBookingWindow:
    def test_slot_opens_14_days_earlier_at_the_same_time(self):
        slot = bucharest(2026, 6, 29, 15, 0)
        assert slot_opens_at(slot) == bucharest(2026, 6, 15, 15, 0)

    def test_bot_starts_two_minutes_before_opening(self):
        slot = bucharest(2026, 6, 29, 15, 0)
        assert bot_starts_at(slot) == bucharest(2026, 6, 15, 14, 58)

    def test_autumn_dst_change_keeps_wall_clock_time(self):
        # Clocks go back on 25 Oct 2026, between 19 Oct and 2 Nov.
        # Subtracting 14 x 24 h would land on 20:00; the slot really opens at 19:00.
        opens = slot_opens_at(slot_datetime("2026-11-02", "19:00"))
        assert (opens.hour, opens.minute) == (19, 0)
        assert opens.date().isoformat() == "2026-10-19"
        assert opens.utcoffset() == timedelta(hours=3)  # summer time (EEST)

    def test_spring_dst_change_keeps_wall_clock_time(self):
        # Clocks go forward on 29 Mar 2026, between 22 Mar and 5 Apr.
        opens = slot_opens_at(slot_datetime("2026-04-05", "10:00"))
        assert (opens.hour, opens.minute) == (10, 0)
        assert opens.date().isoformat() == "2026-03-22"
        assert opens.utcoffset() == timedelta(hours=2)  # winter time (EET)

    def test_opening_is_the_right_absolute_instant_across_dst(self):
        # The scheduler fires on absolute time: 19:00 EEST on 19 Oct is 16:00 UTC.
        opens = slot_opens_at(slot_datetime("2026-11-02", "19:00"))
        assert opens == datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)


class TestPin:
    @pytest.mark.parametrize("pin", ["1234", "0000", "8317"])
    def test_accepts_four_digits(self, pin):
        assert is_valid_pin(pin)

    @pytest.mark.parametrize("pin", ["", "123", "12345", "12a4", "12 4", "١٢٣٤"])
    def test_rejects_anything_the_keypad_cannot_enter(self, pin):
        assert not is_valid_pin(pin)


class TestRestoreAfterRestart:
    SLOT = bucharest(2026, 6, 29, 15, 0)  # opens 15 Jun 15:00, bot starts 14:58

    def test_future_booking_is_rescheduled(self):
        assert restore_action(self.SLOT, bucharest(2026, 6, 10, 9, 0)) == "schedule"

    def test_restart_inside_the_lead_time_runs_immediately(self):
        assert restore_action(self.SLOT, bucharest(2026, 6, 15, 14, 59)) == "run_now"

    def test_restart_exactly_at_bot_start_runs_immediately(self):
        assert restore_action(self.SLOT, bucharest(2026, 6, 15, 14, 58)) == "run_now"

    def test_restart_after_the_slot_opened_is_missed(self):
        assert restore_action(self.SLOT, bucharest(2026, 6, 15, 15, 0)) == "missed"
        assert restore_action(self.SLOT, bucharest(2026, 6, 20, 12, 0)) == "missed"
