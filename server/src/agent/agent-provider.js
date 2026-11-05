export class AgentProvider {
  async plan(_message, _previousTrip) {
    throw new Error("AgentProvider.plan must be implemented by a provider.");
  }
}
