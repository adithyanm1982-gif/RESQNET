import { useStore } from '../store'
// Failure condition used by Mission Control (auto-injected) and by Experiments (identical for all three modes)
export default function PlanEditor() {
  const { plan, setPlan } = useStore()
  return (
    <div className="row" style={{ alignItems: 'flex-end' }}>
      <label className="f">Failure condition
        <select value={plan.type} onChange={(e) => setPlan({ type: e.target.value as any })}>
          <option value="none">None</option><option value="controller_outage">Central controller outage</option>
          <option value="network_partition">Network partition</option><option value="drone_unresponsive">Disconnect one drone</option></select></label>
      {plan.type === 'drone_unresponsive' && <label className="f">Drone<input style={{ width: 70 }} value={plan.drone} onChange={(e) => setPlan({ drone: e.target.value })} /></label>}
      {plan.type !== 'none' && <>
        <label className="f">Inject at tick<input type="number" min={1} style={{ width: 90 }} value={plan.tick} onChange={(e) => setPlan({ tick: Math.max(1, +e.target.value) })} /></label>
        <label className="f">Auto-restore after (ticks, 0 = never)<input type="number" min={0} style={{ width: 150 }} value={plan.restoreAfter} onChange={(e) => setPlan({ restoreAfter: Math.max(0, +e.target.value) })} /></label></>}
    </div>)
}
