# Flow-state tagging

`FlowStateTransform` adds a valve flow-state and its age to records containing
configured sensor fields. It preserves every incoming field and uses record
timestamps rather than the computer clock. The example configuration runs by
itself and tags the `TSG_Temp` and `TSG_Cond` fields found in NBP1406 samples.

Schedule mode repeats open and closed phases around an ISO 8601 anchor. The
start of either phase is reported as `transition` for `transition_seconds`.
Times before the anchor use the same repeating schedule.

Field mode remembers the latest `state_field` value, including observations in
records that contain no tagged sensor value. Add `transition_seconds` alongside
`values`, for example `{1: seawater, 0: filtered}`. Until a state is observed,
the output is `unknown`; an unmapped state is also `unknown` and is warned once
per distinct value. State memory belongs to one transform instance and is not
persisted across restarts.

Load `contrib/deepsignal/configs/flow_state_example.yaml` as a transform config.
Each matching record receives `<id>_flow_state` and
`<id>_flow_state_age_s`. Records with no configured sensor field are returned
unchanged, and `None` remains `None`.
