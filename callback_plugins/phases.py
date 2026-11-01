from ansible.plugins.callback.default import CallbackModule as Default

DOCUMENTATION = """
name: phases
type: stdout
short_description: The default output plus a line as each block starts
description:
  - Prints a block's name when its first task starts, so a quiet run still shows progress.
extends_documentation_fragment:
  - ansible.builtin.default_callback
  - ansible.builtin.result_format_callback
"""


class CallbackModule(Default):
    CALLBACK_NAME = "phases"
    _phase = None

    def v2_playbook_on_task_start(self, task, is_conditional):
        # Bare tasks sit in an unnamed implicit block, so they print nothing
        phase = task._parent.name
        if phase and phase != self._phase:
            self._phase = phase
            self._display.display(phase)
        super().v2_playbook_on_task_start(task, is_conditional)
