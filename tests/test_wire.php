<?php
// Pin wire.php's frames and parser with fixed bytes, no timing involved.
// Run with `php tests/test_wire.php`; core PHP only.
//
// A hand-rolled stand-in for PHPUnit: a TestCase base class, assertSame, and a
// runner that finds every test* method and prints PHPUnit's dots and summary.

// wire.php has no PHP tag, since it is sent as `php -r`, so it loads as eval'd source.
eval(file_get_contents(__DIR__ . "/../src/hello_127/wire.php"));

// The base class: assertions that count themselves and throw on a mismatch.
abstract class TestCase
{
    public int $assertions = 0;

    // Fail unless `$actual` is identical to `$expected`, type included.
    public function assertSame($expected, $actual, string $message = ""): void
    {
        $this->assertions++;
        if ($expected !== $actual) {
            $line = "Failed asserting that " . self::export($actual)
                . " is identical to " . self::export($expected) . ".";
            throw new AssertionError($message === "" ? $line : "$message\n$line");
        }
    }

    // Return `$value` for a failure message, with binary strings as hex.
    private static function export($value): string
    {
        if (is_array($value)) {
            return "[" . implode(", ", array_map([self::class, "export"], $value)) . "]";
        }
        if (is_string($value) && preg_match('/[^\x20-\x7e]/', $value)) {
            return "hex " . bin2hex($value);
        }
        return var_export($value, true);
    }

    // Fail unless `$actual` is null.
    public function assertNull($actual, string $message = ""): void
    {
        $this->assertSame(null, $actual, $message);
    }
}

// Run every test* method of each class, print dots, then the summary. Return 0 or 1.
function run_tests(string ...$classes): int
{
    $tests = 0;
    $assertions = 0;
    $failures = [];
    foreach ($classes as $class) {
        foreach (get_class_methods($class) as $method) {
            if (!str_starts_with($method, "test")) {
                continue;
            }
            $case = new $class();
            $tests++;
            try {
                $case->$method();
                echo ".";
            } catch (AssertionError $error) {
                echo "F";
                $failures[] = "$class::$method\n" . $error->getMessage();
            }
            $assertions += $case->assertions;
        }
    }
    echo "\n\n";
    if ($failures === []) {
        echo "OK ($tests tests, $assertions assertions)\n";
        return 0;
    }
    foreach ($failures as $number => $failure) {
        echo $number + 1, ") $failure\n\n";
    }
    echo "FAILURES!\nTests: $tests, Assertions: $assertions, Failures: ", count($failures), ".\n";
    return 1;
}

// The cases from test_wire.js, in the same order.
final class WireTest extends TestCase
{
    public function testFrameWritesKindConnectionAndLengthBigEndianThenThePayload(): void
    {
        $this->assertSame("\x02\x00\x00\x01\x02\x00\x00\x00\x03abc", frame(DATA, 258, "abc"));
    }

    public function testFrameWithNoPayloadIsTheHeaderAlone(): void
    {
        $this->assertSame("\x03\x00\x00\x00\x07\x00\x00\x00\x00", frame(CLOSE, 7));
    }

    public function testNextFrameWaitsForAWholeHeader(): void
    {
        $this->assertNull(next_frame(""));
        $this->assertNull(next_frame("\x02\x00\x00\x00\x01\x00\x00\x00"));
    }

    public function testNextFrameWaitsForAWholePayload(): void
    {
        $whole = frame(DATA, 1, "hello");
        $this->assertNull(next_frame(substr($whole, 0, -1)));
    }

    public function testNextFrameReadsOneFrameExactlyWithNothingLeft(): void
    {
        $this->assertSame([DATA, 9, "hi", ""], next_frame(frame(DATA, 9, "hi")));
    }

    public function testNextFrameReadsTwoFramesInOneBufferOneAtATime(): void
    {
        [$kind, , $payload, $rest] = next_frame(frame(DATA, 1, "one") . frame(CLOSE, 1));
        $this->assertSame([DATA, "one"], [$kind, $payload]);
        $this->assertSame([CLOSE, 1, "", ""], next_frame($rest));
    }

    public function testNextFrameReadsADataFrameWithAnEmptyPayload(): void
    {
        $this->assertSame([DATA, 4, "", ""], next_frame(frame(DATA, 4, "")));
    }

    public function testAHeaderSplitAtAnyOffsetReadsOnceBothPartsArrive(): void
    {
        $whole = frame(DATA, 5, "split");
        for ($at = 1; $at < HEADER_SIZE; $at++) {
            $first = substr($whole, 0, $at);
            $this->assertNull(next_frame($first), "split at $at");
            [, $conn, $payload] = next_frame($first . substr($whole, $at));
            $this->assertSame([5, "split"], [$conn, $payload], "split at $at");
        }
    }

    public function testAnOpenCarriesItsListenersIndexInTwoBytes(): void
    {
        [$kind, $conn, $payload] = next_frame(frame(OPEN, 3, pack("n", 513)));
        $this->assertSame([OPEN, 3, 513], [$kind, $conn, unpack("n", $payload)[1]]);
    }

    public function testTheLargestConnectionNumberSurvivesTheRoundTrip(): void
    {
        [, $conn] = next_frame(frame(CLOSE, 2 ** 32 - 1));
        $this->assertSame(2 ** 32 - 1, $conn);
    }
}

exit(run_tests(WireTest::class));
