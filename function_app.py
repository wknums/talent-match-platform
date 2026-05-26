"""Azure Functions v2 host entry-point.

A single `FunctionApp` instance is required at the project root for the
Python v2 programming model. Triggers defined in sub-modules are exposed
as `azure.functions.Blueprint` objects and registered here.
"""

import azure.durable_functions as df
import azure.functions as func

from orchestrator.functions.dlq_replay import bp as dlq_replay_bp
from orchestrator.functions.fanout import bp as fanout_bp
from orchestrator.functions.result_intake import bp as result_intake_bp

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

app.register_functions(fanout_bp)
app.register_functions(result_intake_bp)
app.register_functions(dlq_replay_bp)
