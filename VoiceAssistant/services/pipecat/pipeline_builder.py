"""Main pipeline assembly.

Copied from the upstream Pipecat pipeline builder (BSD-2-Clause; see LICENSE).
Recording, voicemail, metrics, workflow-run and turn-logging branches have been
removed; the processor ordering of ``build_pipeline`` is unchanged.
"""

from pipecat.pipeline.pipeline import Pipeline


def build_pipeline(
    transport,
    stt,
    llm,
    tts,
    user_context_aggregator,
    assistant_context_aggregator,
    observer=None,
):
    """Build the main pipeline with all components.

    Processor order matches the original pipeline:
    transport input -> STT -> user context aggregator -> LLM -> TTS ->
    transport output -> assistant context aggregator.
    """
    processors = [
        transport.input(),  # Transport user input
    ]
    if observer is not None:
        processors.append(observer)
    processors.extend([
        stt,
        user_context_aggregator,
        llm,  # LLM
        tts,  # TTS
        transport.output(),  # Transport bot output
        assistant_context_aggregator,  # Assistant spoken responses
    ])

    return Pipeline(processors)


def build_realtime_pipeline(
    transport,
    realtime_llm,
    user_context_aggregator,
    assistant_context_aggregator,
):
    """Build a speech-to-speech pipeline for a realtime LLM service.

    The realtime service handles STT and TTS internally, so those processors are
    intentionally absent. Processor order follows the upstream realtime layout:
    transport input -> user context aggregator -> realtime LLM -> transport
    output -> assistant context aggregator. UI reporting is attached as a
    pipeline observer instead of an in-chain processor.
    """
    return Pipeline(
        [
            transport.input(),
            user_context_aggregator,
            realtime_llm,
            transport.output(),
            assistant_context_aggregator,
        ]
    )
