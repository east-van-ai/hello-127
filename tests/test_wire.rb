# Pin wire.rb's frames and parser with fixed bytes, no timing involved.
# Run with `ruby tests/test_wire.rb`; Minitest ships with Ruby as a bundled gem.

require "minitest/autorun"
require_relative "../src/hello_127/wire"

# The cases from test_wire.js, in the same order.
class WireTest < Minitest::Test
  def test_frame_writes_kind_connection_and_length_big_endian_then_the_payload
    assert_equal "\x02\x00\x00\x01\x02\x00\x00\x00\x03abc".b, frame(DATA, 258, "abc")
  end

  def test_frame_with_no_payload_is_the_header_alone
    assert_equal "\x03\x00\x00\x00\x07\x00\x00\x00\x00".b, frame(CLOSE, 7)
  end

  def test_next_frame_waits_for_a_whole_header
    assert_nil next_frame("".b)
    assert_nil next_frame("\x02\x00\x00\x00\x01\x00\x00\x00".b)
  end

  def test_next_frame_waits_for_a_whole_payload
    whole = frame(DATA, 1, "hello")
    assert_nil next_frame(whole.byteslice(0, whole.bytesize - 1))
  end

  def test_next_frame_reads_one_frame_exactly_with_nothing_left
    assert_equal [DATA, 9, "hi", ""], next_frame(frame(DATA, 9, "hi"))
  end

  def test_next_frame_reads_two_frames_in_one_buffer_one_at_a_time
    kind, _, payload, rest = next_frame(frame(DATA, 1, "one") + frame(CLOSE, 1))
    assert_equal [DATA, "one"], [kind, payload]
    assert_equal [CLOSE, 1, "", ""], next_frame(rest)
  end

  def test_next_frame_reads_a_data_frame_with_an_empty_payload
    assert_equal [DATA, 4, "", ""], next_frame(frame(DATA, 4, ""))
  end

  def test_a_header_split_at_any_offset_reads_once_both_parts_arrive
    whole = frame(DATA, 5, "split")
    (1...HEADER_SIZE).each do |at|
      first = whole.byteslice(0, at)
      assert_nil next_frame(first), "split at #{at}"
      _, conn, payload = next_frame(first + whole.byteslice(at..))
      assert_equal [5, "split"], [conn, payload], "split at #{at}"
    end
  end

  def test_an_open_carries_its_listeners_index_in_two_bytes
    kind, conn, payload = next_frame(frame(OPEN, 3, [513].pack("n")))
    assert_equal [OPEN, 3, 513], [kind, conn, payload.unpack1("n")]
  end

  def test_the_largest_connection_number_survives_the_round_trip
    _, conn = next_frame(frame(CLOSE, 2**32 - 1))
    assert_equal 2**32 - 1, conn
  end
end
