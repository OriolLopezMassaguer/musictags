"""A job is a list of steps: order, stop-on-failure, and a cooperative stop.

The chains that ship (CHAINS) start with `scan`, whose argv needs a real library on
disk, so the tests register a chain of their own instead of depending on config.sh.
"""

import os
import sys
import time
import unittest

from gui import runner as R

PY = [sys.executable, "-u", "-c"]


def py(code):
    return PY + [code]


def run(plan, stop_after=None, force=False, limit=25):
    """Run a plan to completion, optionally stopping it part way."""
    job = R.Job(plan)
    job.start()
    if stop_after is not None:
        time.sleep(stop_after)
        job.stop(force=force)
    t0 = time.time()
    while job.running and time.time() - t0 < limit:
        time.sleep(0.05)
    return job


class ChainPlan(unittest.TestCase):
    """build_chain: the right steps, with every argv validated before anything runs."""

    def setUp(self):
        self.chain = {"id": "t", "label": "Prueba", "steps": ["analyze", "propose"]}
        R.BY_CHAIN["t"] = self.chain
        self.addCleanup(R.BY_CHAIN.pop, "t", None)

    def test_steps_in_order_with_their_own_params(self):
        chain, plan = R.build_chain("t", {"propose": {"only": ["genre", "style"]}})
        self.assertEqual(chain["label"], "Prueba")
        self.assertEqual([sid for sid, _ in plan], ["analyze", "propose"])
        self.assertIn("--only", plan[1][1])
        self.assertIn("genre,style", plan[1][1])

    def test_defaults_when_a_step_has_no_params(self):
        _, plan = R.build_chain("t", {})
        self.assertIn("--fuzzy", plan[0][1])           # [analyze] default is True

    def test_unknown_chain(self):
        with self.assertRaises(R.BadRequest):
            R.build_chain("nope", {})

    def test_a_bad_param_fails_before_anything_starts(self):
        with self.assertRaises(R.BadRequest):
            R.build_chain("t", {"propose": {"path": "/etc"}})

    def test_a_chain_never_asks_for_write(self):
        R.BY_CHAIN["t"]["steps"] = ["apply"]
        _, plan = R.build_chain("t", {})
        self.assertNotIn("--apply", plan[0][1])        # dry run, always


class ChainRun(unittest.TestCase):

    def test_runs_every_step_in_order(self):
        job = run([("analyze", py("print('uno')")),
                   ("propose", py("print('dos')")),
                   ("apply", py("print('tres')"))])
        self.assertEqual(job.returncode, 0)
        self.assertEqual([l for l in job.lines if l in ("uno", "dos", "tres")],
                         ["uno", "dos", "tres"])
        self.assertEqual(job.total, 3)

    def test_banner_between_steps_but_not_for_a_single_one(self):
        job = run([("analyze", py("print('uno')")), ("propose", py("print('dos')"))])
        self.assertTrue(any("===== 1/2  analyze =====" in l for l in job.lines))
        job = run([("analyze", py("print('solo')"))])
        self.assertFalse(any(l.startswith("=====") for l in job.lines))

    def test_stops_at_the_first_failure(self):
        job = run([("analyze", py("print('uno')")),
                   ("propose", py("raise SystemExit(3)")),
                   ("apply", py("print('NUNCA')"))])
        self.assertEqual(job.returncode, 3)
        self.assertNotIn("NUNCA", job.lines)
        self.assertTrue(any("la cadena se detiene" in l for l in job.lines))

    def test_stop_ends_the_step_and_cancels_the_rest(self):
        waiter = ("import core, time\n"
                  "core.handle_interrupts()\n"
                  "print('trabajando', flush=True)\n"
                  "while not core.stopping(): time.sleep(.05)\n"
                  "print('parada limpia')\n"
                  "raise SystemExit(core.EXIT_INTERRUPTED)")
        job = run([("analyze", py(waiter)), ("propose", py("print('NUNCA')"))],
                  stop_after=1.5)
        self.assertEqual(job.returncode, R.EXIT_INTERRUPTED)
        self.assertTrue(job.stopped)
        self.assertIn("parada limpia", job.lines)      # it chose when to stop
        self.assertNotIn("NUNCA", job.lines)

    def test_force_kills_a_step_that_ignores_the_signal(self):
        deaf = ("import signal, time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "print('sordo', flush=True)\n"
                "time.sleep(60)")
        job = run([("analyze", py(deaf))], stop_after=1.5, force=True)
        self.assertFalse(job.running)
        self.assertTrue(job.stopped)
        self.assertEqual(job.returncode, -9)           # SIGKILL

    def test_log_file_holds_the_whole_chain(self):
        job = run([("analyze", py("print('uno')")), ("propose", py("print('dos')"))])
        with open(job.log_path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("uno", text)
        self.assertIn("dos", text)
        self.assertIn("===== 2/2  propose =====", text)
        os.unlink(job.log_path)

    def test_as_dict_keeps_the_keys_the_templates_use(self):
        job = run([("analyze", py("print('uno')"))])
        d = job.as_dict()
        for key in ("id", "step", "label", "running", "returncode", "command",
                    "elapsed", "lines", "index", "total", "steps", "stopped"):
            self.assertIn(key, d)
        self.assertEqual(d["total"], 1)
        self.assertEqual(d["steps"], ["analyze"])


class OneAtATime(unittest.TestCase):

    def test_a_second_launch_is_refused_while_one_runs(self):
        runner = R.Runner()
        job = R.Job([("analyze", py("import time; time.sleep(5)"))])
        runner.jobs[job.id] = job
        runner.current = job
        job.start()
        self.addCleanup(job.stop, True)
        self.assertTrue(runner.busy())
        with self.assertRaises(R.BadRequest):
            runner.start("analyze", {})


if __name__ == "__main__":
    unittest.main()
