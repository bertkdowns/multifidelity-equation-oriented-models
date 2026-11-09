"""Check no-step equilibrium, conservation and time-grid refinement; plot the run."""
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent
LOOPS=['source_tank','warm_tank','hot_tank']


def load(prefix):
    report=json.loads((HERE/f'{prefix}_report.json').read_text())
    snapshot=json.loads((HERE/f'{prefix}_results.json').read_text())
    variables={r['variable_path']:{e['index'][0] if e['index'] else None:e['value']
                                 for e in r['entries']} for r in snapshot['variables']}
    times=sorted(variables['source_tank.inventory.energy'])
    return report,variables,times


def conservation(variables,times):
    v=lambda p,t:variables[p][t]
    max_mass=0.;max_energy=0.;total_energy_input=0.
    for previous,t in zip(times,times[1:]):
        dt=t-previous
        delta_mass=sum(v(a+'.inventory.mass',t)-v(a+'.inventory.mass',previous) for a in LOOPS)
        delta_energy=sum(v(a+'.inventory.energy',t)-v(a+'.inventory.energy',previous) for a in LOOPS)
        net_mass=v('makeup_state.state.flow',t)-v('steam_outlet.flow',t)
        net_energy=(v('phnix.performance.heating_duty',t)+v('sghp.performance.electrical_power',t)
                    +v('performance.pump_power',t)-v('cooling_exchanger.performance.heat_duty',t)
                    +v('makeup_state.state.flow',t)*v('makeup_state.state.enthalpy',t)
                    -v('steam_outlet.flow',t)*v('steam_outlet.enthalpy',t)
                    -sum(v(a+'.loss.heat',t) for a in LOOPS))
        max_mass=max(max_mass,abs(delta_mass-dt*net_mass))
        max_energy=max(max_energy,abs(delta_energy-dt*net_energy))
        total_energy_input+=dt*net_energy
    energy_change=sum(v(a+'.inventory.energy',times[-1])-v(a+'.inventory.energy',times[0]) for a in LOOPS)
    return dict(max_step_mass_error_kg=max_mass,max_step_energy_error_J=max_energy,
                inventory_energy_change_J=energy_change,integrated_net_energy_J=total_energy_input,
                total_energy_error_J=abs(energy_change-total_energy_input))


if __name__=='__main__':
    coarse,cv,ct=load('thermal_step')
    fine,fv,ft=load('thermal_step_refined')
    zero,zv,zt=load('thermal_no_step')
    assert all(r['solved'] for r in [coarse,fine,zero])
    checks={name:conservation(v,t) for name,v,t in [('step',cv,ct),('refined',fv,ft),('no_step',zv,zt)]}
    temperature_paths=[a+'.inventory.temperature' for a in LOOPS]
    checks['no_step_max_temperature_drift_K']=max(abs(zv[p][t]-zv[p][zt[0]]) for p in temperature_paths for t in zt)
    checks['maximum_coincident_temperature_difference_K']=max(abs(cv[p][t]-fv[p][t]) for p in temperature_paths for t in ct)
    checks['source_temperature_rise_K']=cv[temperature_paths[0]][ct[-1]]-cv[temperature_paths[0]][ct[0]]
    for name in ['step','refined','no_step']:
        assert checks[name]['max_step_mass_error_kg']<1e-6
        assert checks[name]['max_step_energy_error_J']<1e-2
        assert checks[name]['total_energy_error_J']<1e-2
    assert checks['no_step_max_temperature_drift_K']<1e-6
    assert checks['maximum_coincident_temperature_difference_K']<1e-3
    assert checks['source_temperature_rise_K']>0
    assert all(cv[temperature_paths[0]][t]>=cv[temperature_paths[0]][p]-1e-8 for p,t in zip(ct,ct[1:]))
    checks['verified']=True
    (HERE/'thermal_verification.json').write_text(json.dumps(checks,indent=2)+'\n')
    with (HERE/'thermal_step.csv').open('w',newline='') as file:
        writer=csv.writer(file)
        writer.writerow(['time_s','source_C','warm_C','hot_C','steam_kg_h','PHNIX_kW'])
        for t in ct:
            writer.writerow([t,*[cv[p][t]-273.15 for p in temperature_paths],
                             cv['steam_outlet.flow'][t]*3600,cv['phnix.performance.electrical_power'][t]/1000])
    fig,axes=plt.subplots(3,1,figsize=(8,7),sharex=True,layout='constrained')
    axes[0].step(ct,[cv['phnix.performance.electrical_power'][t]/1000 for t in ct],where='pre',color='#147d92')
    axes[0].set_ylabel('PHNIX power (kW)')
    for p,label,color in zip(temperature_paths,['Source loop','Warm-water loop','Hot-water loop'],['#147d92','#df8a25','#ae4b60']):
        axes[1].plot(ct,[cv[p][t]-cv[p][ct[0]] for t in ct],label=label,color=color)
    axes[1].plot(ft,[fv[temperature_paths[0]][t]-fv[temperature_paths[0]][ft[0]] for t in ft],
                 linestyle='--',color='#164254',linewidth=1,label='Source, 30 s grid')
    axes[1].set_ylabel('Temperature change (K)');axes[1].legend(fontsize=8,ncol=2)
    axes[2].plot(ct,[cv['steam_outlet.flow'][t]*3600 for t in ct],color='#147d92')
    steam=cv['steam_outlet.flow'][ct[0]]*3600
    axes[2].set_ylim(steam-.01,steam+.01);axes[2].set_ylabel('Steam (kg/h)');axes[2].set_xlabel('Time (s)')
    for ax in axes:
        ax.axvline(120,color='#777777',linestyle=':',linewidth=1);ax.grid(alpha=.2)
        ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Aggregate SGHP plant: +10% PHNIX power at 120 s\nInitial water inventory 100 L per loop; COPs and SGHP duties held constant',fontsize=11)
    fig.savefig(HERE/'thermal_response.png',dpi=160)
    plt.close(fig)
    print(json.dumps(checks,indent=2))
