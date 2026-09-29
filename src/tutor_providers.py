"""Automatic tutor API access is disabled; responses are pasted by the learner."""

class TutorError(ValueError):
    pass


def generate(job):
    raise TutorError('Automatic API tutoring is disabled. Paste a tutor response instead.')
