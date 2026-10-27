import { useMemo, useState } from 'react'
import { useStore } from '../store'
import type { CustomFailureEvent, CustomFailureType } from '../api'
import { validateCustomFailurePlan } from '../api'

const titles: Record<CustomFailureType, string> = {
  controller_outage: 'Controller outage',
  network_partition: 'Network partition',
  drone_unresponsive: 'Unresponsive drone',
}

function createEvent(type: CustomFailureType, droneIds: string[]): CustomFailureEvent {
  const base = { start_tick: 1, restore_tick: 20 }
  if (type === 'drone_unresponsive') return { ...base, type, restore_tick: null, drone_id: droneIds[0] || '' }
  if (type === 'controller_outage') return {
    ...base, type,
    reconnection: { detect_timeout_ticks: 3, reconnect_delay_ticks: 3, resync_time_ticks: 4 },
  }
  const split = Math.ceil(droneIds.length / 2)
  return {
    ...base, type,
    groups: [
      { group_id: 'A', drone_ids: droneIds.slice(0, split), has_controller_link: true },
      { group_id: 'B', drone_ids: droneIds.slice(split), has_controller_link: false },
    ],
    reconnection: { detect_timeout_ticks: 3, reconnect_delay_ticks: 4, resync_time_ticks: 6 },
  }
}

export default function PlanEditor() {
  const {
    failureSource, setFailureSource, failId, setFailScenario, failScen,
    customPlan, setCustomPlan, scenarioId, droneCfg,
  } = useStore()
  const [newType, setNewType] = useState<CustomFailureType>('controller_outage')
  const selected = failScen.find((item: any) => item.failure_scenario_id === failId)
  const droneIds: string[] = useMemo(() => (
    droneCfg?.fleets?.find((fleet: any) => fleet.scenario_id === scenarioId)?.drones || []
  ).map((drone: any) => drone.id), [droneCfg, scenarioId])
  const validation = failureSource === 'custom' ? validateCustomFailurePlan(customPlan, droneIds) : []

  const replaceEvent = (index: number, event: CustomFailureEvent) => {
    setCustomPlan(customPlan.map((current, i) => i === index ? event : current))
  }
  const updateNumber = (event: CustomFailureEvent, field: 'start_tick' | 'restore_tick', raw: string) => {
    const value = raw === '' ? null : Number(raw)
    replaceEvent(customPlan.indexOf(event), { ...event, [field]: value } as CustomFailureEvent)
  }
  const updateRecovery = (event: CustomFailureEvent, field: 'detect_timeout_ticks' | 'reconnect_delay_ticks' | 'resync_time_ticks', raw: string) => {
    if (!event.reconnection) return
    replaceEvent(customPlan.indexOf(event), {
      ...event,
      reconnection: { ...event.reconnection, [field]: raw === '' ? Number.NaN : Number(raw) },
    } as CustomFailureEvent)
  }
  const setIsolatedDrone = (event: Extract<CustomFailureEvent, { type: 'network_partition' }>, droneId: string, checked: boolean) => {
    const isolated = new Set(event.groups.filter((group) => !group.has_controller_link).flatMap((group) => group.drone_ids))
    checked ? isolated.add(droneId) : isolated.delete(droneId)
    const next: CustomFailureEvent = {
      ...event,
      groups: [
        { group_id: 'A', drone_ids: droneIds.filter((id) => !isolated.has(id)), has_controller_link: true },
        { group_id: 'B', drone_ids: droneIds.filter((id) => isolated.has(id)), has_controller_link: false },
      ],
    }
    replaceEvent(customPlan.indexOf(event), next)
  }

  return (
    <div className="custom-plan-editor">
      <label className="f">Failure-plan source
        <select value={failureSource} onChange={(event) => setFailureSource(event.target.value as 'none' | 'predefined' | 'custom')}>
          <option value="none">No failure schedule</option>
          <option value="predefined">Predefined dataset schedule</option>
          <option value="custom">Custom failure plan</option>
        </select>
      </label>

      {failureSource === 'predefined' && <div className="custom-plan-panel">
        <label className="f">Failure schedule from failure_scenarios.json
          <select value={failId} onChange={(event) => setFailScenario(event.target.value)}>
            <option value="">— choose a predefined schedule —</option>
            {failScen.map((item: any) => <option key={item.failure_scenario_id} value={item.failure_scenario_id}>{item.title}</option>)}
          </select>
        </label>
        {selected
          ? <><p className="mut">{selected.description} Events retain the dataset’s declared timing and recovery metadata.</p>
            {!!selected.events?.length && <table><thead><tr><th>Event</th><th>Type</th><th>Start</th><th>Restore</th></tr></thead><tbody>
              {selected.events.map((event: any) => <tr key={event.id}><td className="mono">{event.id}</td><td>{event.type}</td><td className="mono">{event.start_s}s</td><td className="mono">{event.end_s == null ? 'never' : `${event.end_s}s`}</td></tr>)}
            </tbody></table>}
          </>
          : <p className="mut">Choose a dataset schedule to install before the run’s first tick.</p>}
      </div>}

      {failureSource === 'custom' && <div className="custom-plan-panel">
        <p className="mut">Author a tick-based plan for this scenario. The plan is stored in this browser and installed on each run before its first tick.</p>
        <div className="row plan-add">
          <label className="f">Add event<select value={newType} onChange={(event) => setNewType(event.target.value as CustomFailureType)}>
            {Object.entries(titles).map(([type, title]) => <option key={type} value={type}>{title}</option>)}
          </select></label>
          <button type="button" disabled={customPlan.length >= 10} onClick={() => setCustomPlan([...customPlan, createEvent(newType, droneIds)])}>Add event</button>
        </div>
        {!customPlan.length && <p className="mut">Add at least one event. Plans support controller outages, network partitions, and unresponsive drones.</p>}
        {customPlan.map((event, index) => <section className="custom-event" key={`${event.type}-${index}`}>
          <div className="custom-event-head"><b>Event {index + 1}: {titles[event.type]}</b>
            <button type="button" className="danger sm" onClick={() => setCustomPlan(customPlan.filter((_, i) => i !== index))}>Remove</button>
          </div>
          <div className="custom-event-fields">
            <label className="f">Failure type<select value={event.type} onChange={(change) => replaceEvent(index, {
              ...createEvent(change.target.value as CustomFailureType, droneIds),
              start_tick: event.start_tick,
              restore_tick: event.restore_tick,
            })}>{Object.entries(titles).map(([type, title]) => <option key={type} value={type}>{title}</option>)}</select></label>
            <label className="f">Start tick<input type="number" min={1} max={100000} step={1} value={event.start_tick} onChange={(change) => updateNumber(event, 'start_tick', change.target.value)} /></label>
            <label className="f">Restore at tick<input type="number" min={event.start_tick + 1} max={100000} step={1} value={event.restore_tick ?? ''} placeholder={event.type === 'drone_unresponsive' ? 'never' : 'required'} disabled={event.type === 'drone_unresponsive' && event.restore_tick == null} onChange={(change) => updateNumber(event, 'restore_tick', change.target.value)} /></label>
            {event.type === 'drone_unresponsive' && <label className="f check-field"><input type="checkbox" checked={event.restore_tick == null} onChange={(change) => replaceEvent(index, { ...event, restore_tick: change.target.checked ? null : event.start_tick + 1 })} />Never returns</label>}
            {event.type === 'drone_unresponsive' && <label className="f">Target drone<select value={event.drone_id} onChange={(change) => replaceEvent(index, { ...event, drone_id: change.target.value })}>
              <option value="">Choose drone</option>{droneIds.map((id) => <option key={id} value={id}>{id}</option>)}
            </select></label>}
          </div>
          {event.type === 'network_partition' && <fieldset className="partition-editor"><legend>Drones outside the controller-linked group</legend>
            {!droneIds.length && <p className="mut">Load the selected scenario’s drone configuration to edit partition groups.</p>}
            {droneIds.map((id) => <label key={id}><input type="checkbox" checked={event.groups.some((group) => !group.has_controller_link && group.drone_ids.includes(id))} onChange={(change) => setIsolatedDrone(event, id, change.target.checked)} /> {id}</label>)}
          </fieldset>}
          {event.reconnection && <div className="custom-event-fields recovery-fields">
            {(['detect_timeout_ticks', 'reconnect_delay_ticks', 'resync_time_ticks'] as const).map((field) => <label className="f" key={field}>{field.replace(/_/g, ' ')}<input type="number" min={0} max={10000} step={1} value={event.reconnection?.[field] ?? ''} onChange={(change) => updateRecovery(event, field, change.target.value)} /></label>)}
          </div>}
        </section>)}
        {validation.length > 0 && <ul className="err plan-errors">{validation.map((error) => <li key={error}>{error}</li>)}</ul>}
        <p className="mut">Controller and partition recovery metadata is entered in ticks. The backend converts ticks using the dataset’s configured tick duration. A drone with “Never returns” uses the existing null-end semantics.</p>
        <p className="mut">Controller-outage fallback and partition-scoped coordination are implemented for hybrid runs. In other modes, those events are reported in the event lifecycle; the editor does not claim a controller or network operational effect there.</p>
        <p className="mut">Packet loss, message delay, battery overrides, and no-fly activation are not available here: the engine does not apply their operational effects.</p>
      </div>}

      {failureSource === 'none' && <p className="mut">No failure schedule will be installed for this run.</p>}
    </div>
  )
}
