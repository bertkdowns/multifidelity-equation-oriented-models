"""Verify and plot the same thermal experiment with the detailed SGHP cycle."""
import csv
import json
from pathlib import Path
import matplotlib.pyplot as plt
from verify_thermal_dynamics import load, conservation

HERE=Path(__file__).resolve().parent


if __name__=='__main__':
    aggregate,av,at=load('thermal_step')
    coarse,cv,ct=load('thermal_cycle_step')
    fine,fv,ft=load('thermal_cycle_step_refined')
    zero,zv,zt=load('thermal_cycle_no_step')
    assert all(r['solved'] for r in [aggregate,coarse,fine,zero])
    loops=['source_tank','warm_tank','hot_tank']
    paths=[a+'.inventory.temperature' for a in loops]
    checks={name:conservation(v,t) for name,v,t in [('cycle',cv,ct),('refined',fv,ft),('no_step',zv,zt)]}
    checks['no_step_temperature_drift_K']=max(abs(zv[p][t]-zv[p][zt[0]]) for p in paths for t in zt)
    checks['maximum_coincident_temperature_difference_K']=max(abs(cv[p][t]-fv[p][t]) for p in paths for t in ct)
    checks['maximum_coincident_steam_difference_kg_h']=max(abs(cv['steam_outlet.flow'][t]-fv['steam_outlet.flow'][t])*3600 for t in ct)
    checks['initial_temperature_difference_K']=max(abs(cv[p][ct[0]]-av[p][at[0]]) for p in paths)
    checks['final']={
        'source_temperature_C':cv[paths[0]][ct[-1]]-273.15,
        'aggregate_source_temperature_C':av[paths[0]][at[-1]]-273.15,
        'cop':cv['sghp.performance.cop'][ct[-1]],
        'steam_kg_h':cv['steam_outlet.flow'][ct[-1]]*3600,
        'aggregate_steam_kg_h':av['steam_outlet.flow'][at[-1]]*3600,
        'hot_inventory_mass_change_kg':cv['hot_tank.inventory.mass'][ct[-1]]-cv['hot_tank.inventory.mass'][ct[0]],
        'refined_source_temperature_C':fv[paths[0]][ft[-1]]-273.15,
        'refined_cop':fv['sghp.performance.cop'][ft[-1]],
        'refined_steam_kg_h':fv['steam_outlet.flow'][ft[-1]]*3600,
    }
    checks['minimum_compressor_inlet_vapor_fraction']=min(cv['sghp.compressor.inlet_state.properties.vapor_fraction'].values())
    checks['minimum_level_m']=min(cv[a+'.inventory.level'][t] for a in loops for t in ct)
    for name in ['cycle','refined','no_step']:
        assert checks[name]['max_step_mass_error_kg']<1e-6
        assert checks[name]['max_step_energy_error_J']<.1
        assert checks[name]['total_energy_error_J']<.5
    assert checks['initial_temperature_difference_K']<1e-7
    assert checks['no_step_temperature_drift_K']<1e-7
    assert checks['maximum_coincident_temperature_difference_K']<.1
    assert checks['maximum_coincident_steam_difference_kg_h']<.2
    assert checks['minimum_compressor_inlet_vapor_fraction']>1-1e-7
    assert checks['minimum_level_m']>0
    assert checks['final']['steam_kg_h']>checks['final']['aggregate_steam_kg_h']
    checks['verified']=True
    (HERE/'thermal_cycle_verification.json').write_text(json.dumps(checks,indent=2)+'\n')
    with (HERE/'thermal_cycle_step.csv').open('w',newline='') as file:
        writer=csv.writer(file)
        writer.writerow(['time_s','source_C','warm_C','hot_C','steam_kg_h','COP','hot_inventory_kg'])
        for t in ct:
            writer.writerow([t,*[cv[p][t]-273.15 for p in paths],cv['steam_outlet.flow'][t]*3600,
                             cv['sghp.performance.cop'][t],cv['hot_tank.inventory.mass'][t]])
    fig,axes=plt.subplots(2,2,figsize=(10,7),sharex=True,layout='constrained')
    fields=[(paths[0],'Source water (°C)',lambda v:v-273.15),
            ('sghp.performance.cop','SGHP COP',lambda v:v),
            ('steam_outlet.flow','Steam (kg/h)',lambda v:v*3600),
            ('hot_tank.inventory.mass','Hot-loop inventory (kg)',lambda v:v)]
    for ax,(path,label,convert) in zip(axes.flat,fields):
        ax.plot(at,[convert(av[path][t]) for t in at],label='Aggregate SGHP',color='#dd8a2b')
        ax.plot(ct,[convert(cv[path][t]) for t in ct],label='Detailed SGHP, 60 s grid',color='#147d92')
        ax.plot(ft,[convert(fv[path][t]) for t in ft],label='Detailed SGHP, 30 s grid',color='#214459',linestyle='--',linewidth=1)
        ax.axvline(120,color='#777',linestyle=':',linewidth=1);ax.grid(alpha=.2)
        ax.spines[['top','right']].set_visible(False);ax.set_ylabel(label)
    axes[0,0].legend(fontsize=8)
    for ax in axes[1]: ax.set_xlabel('Time (s)')
    fig.suptitle('Same plant and PHNIX power step; aggregate vs detailed SGHP\n100 L initial inventory per loop; detailed compressor pressure rise held constant',fontsize=11)
    fig.savefig(HERE/'thermal_cycle_comparison.png',dpi=160);plt.close(fig)
    print(json.dumps(checks,indent=2))
