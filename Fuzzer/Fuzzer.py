import time
import random

from cocotb.decorators import coroutine
from RTLSim.host import ILL_MEM, SUCCESS, TIME_OUT, ASSERTION_FAIL

from src.utils import *
from src.multicore_manager import proc_state


@coroutine
def Run(dut, toplevel,
        num_iter=1, template='Template', in_file=None,
        out='output', record=False, cov_log=None,
        multicore=0, manager=None, proc_num=0, start_time=0, start_iter=0, start_cov=0,
        prob_intr=0, no_guide=False, debug=False, find_bug=False,
        ADD_ANTLR4=False,ADD_CONTROL=False,ADD_POC=False):

    assert toplevel in ['RocketTile', 'BoomTile' ], \
        '{} is not toplevel'.format(toplevel)

    random.seed(time.time() * (proc_num + 1))

    (mutator, preprocessor, isaHost, rtlHost, checker) = \
        setup(dut, toplevel, template, out, proc_num, debug, no_guide=no_guide)

    if in_file: num_iter = 1

    stop = [ proc_state.NORMAL ]
    mNum = 0
    cNum = 0
    iNum = 0
    last_coverage = 0

    debug_print('[DifuzzRTL] Start Fuzzing', debug)

    if multicore:
        yield manager.cov_restore(dut)

    for it in range(num_iter):
        debug_print('[DifuzzRTL] Iteration [{}]'.format(it), debug)

        if multicore:
            if it == 0:
                mutator.update_corpus(out + '/corpus', 1000)
            elif it % 1000 == 0:
                mutator.update_corpus(out + '/corpus')

        assert_intr = False
        if random.random() < prob_intr:
            assert_intr = True
        dir = '/home/host/difuzz-rtl/Fuzzer/'+preprocessor.base
        if in_file: (sim_input, data, assert_intr) = mutator.read_siminput(in_file)
        else: (sim_input, data) = mutator.get(dir, it, ADD_POC, ADD_CONTROL,ADD_ANTLR4,assert_intr = assert_intr)

        if debug:
            print('[DifuzzRTL] Fuzz Instructions')
            for inst, INT in zip(sim_input.get_insts(), sim_input.ints + [0]):
                print('{:<50}{:04b}'.format(inst, INT))

        (isa_input, rtl_input, symbols) = preprocessor.process(sim_input, data, assert_intr, num_iter = it)

        if isa_input and rtl_input:
            ret = run_isa_test(isaHost, isa_input, stop, out, proc_num)
            if ret == proc_state.ERR_ISA_TIMEOUT: continue
            elif ret == proc_state.ERR_ISA_ASSERT: break

            try:
                (ret, coverage) = yield rtlHost.run_test(rtl_input, assert_intr)
            except:
                stop[0] = proc_state.ERR_RTL_SIM
                break

            if assert_intr and ret == SUCCESS:
                (intr_prv, epc) = checker.check_intr(symbols)
                if epc != 0:
                    preprocessor.write_isa_intr(isa_input, rtl_input, epc)
                    ret = run_isa_test(isaHost, isa_input, stop, out, proc_num, True)
                    if ret == proc_state.ERR_ISA_TIMEOUT: continue
                    elif ret == proc_state.ERR_ISA_ASSERT: break
                else: continue

            cause = '-'
            match = False
            if ret == SUCCESS:
                match = checker.check(symbols)
            elif ret == ILL_MEM:
                match = True
                # debug_print('[DifuzzRTL] Memory access outside DRAM -- {}'. \
                #             format(iNum), debug, True)
                # if record:
                #     save_mismatch(out, proc_num, out + '/illegal',
                #                   sim_input, data, iNum)
                iNum += 1

            if not match or ret not in [SUCCESS, ILL_MEM]:
                if multicore:
                    mNum = manager.read_num('mNum')
                    manager.write_num('mNum', mNum + 1)

                if record:
                    save_mismatch(out, proc_num, out + '/mismatch',
                                  sim_input, data, mNum)

                mNum += 1
                if ret == TIME_OUT: cause = 'Timeout'
                elif ret == ASSERTION_FAIL: cause = 'Assertion fail'
                else: cause = 'Mismatch'

                debug_print('[DifuzzRTL] Bug -- {} [{}]'. \
                            format(mNum, cause), debug, not match or (ret != SUCCESS))

            if coverage > last_coverage:
                if multicore:
                    cNum = manager.read_num('cNum')
                    manager.write_num('cNum', cNum + 1)

                if record:
                    save_file(cov_log, 'a', '{:<10}\t{:<10}\t{:<10}\n'.
                              format(time.time() - start_time, start_iter + it,
                                     start_cov + coverage))
                    sim_input.save(out + '/corpus/id_{}.si'.format(cNum))

                cNum += 1
                mutator.add_corpus(sim_input)
                last_coverage = coverage
                debug_print('[DifuzzRTL] Iteration [{}],time is {}, coverage is {}'.format(it,time.time() - start_time,coverage),True)

            mutator.update_phase(it)

        else:
            stop[0] = proc_state.ERR_COMPILE
            # Compile failed
            break

    if multicore:
        save_err(out, proc_num, manager, stop[0])
        manager.set_state(proc_num, stop[0])

    debug_print('[DifuzzRTL] Stop Fuzzing', debug)

    if multicore:
        yield manager.cov_store(dut, proc_num)
        manager.store_covmap(proc_num, start_time, start_iter, num_iter)

    if find_bug and num_iter == 1:
        fd = open(in_file, 'r')
        bug_fd_lines = fd.readlines()
        fd.close()
        start_cnt = -1
        end_cnt = -1
        ass = []
        ass_end = []
        for i in range(len(bug_fd_lines)):
            if bug_fd_lines[i].startswith("_l0"):
                start_cnt = i
            elif "data:" in bug_fd_lines[i]:
                end_cnt = i
            if start_cnt == -1:
                ass.append(bug_fd_lines[i])
            if end_cnt != -1:
                ass_end.append(bug_fd_lines[i])
            
        #print(start_cnt,end_cnt)
        assembly = []
        word_cnt = 0
        for i in range(end_cnt-start_cnt+1):
            #todo: use ERfen
            assemb = bug_fd_lines[start_cnt:start_cnt+i+1]
            line_cnt = 0
            for asss in assemb:
                
                if asss.startswith("_l"):
                    t = asss.find(':')
                    #print('t is at:{}'.format(t))
                    word_cnt = eval(asss[2:t])
                    #print(word_cnt)
                if "_l" in asss[2:]:
                    ass_list = asss[2:].split(', ')
                    for asl in ass_list:
                        if asl.startswith("_l"):
                            word_L_cnt = eval(asl[2:5])
                            print("!!!",word_L_cnt,word_cnt)
                            if word_L_cnt > word_cnt:
                                assemb[line_cnt] = "\t\t\tnop"
                line_cnt += 1
            assembly = ass + assemb + ass_end
            fd = open('/home/host/difuzz-rtl/Fuzzer/'+preprocessor.base+'/asm_debug_si/bug_{}.si'.format(i),'w')
            print('/home/host/difuzz-rtl/Fuzzer/'+preprocessor.base+'/asm_debug_si/bug_{}.si'.format(i))
            for j in range(len(assembly)):
                fd.write(assembly[j])
            fd.close()

            in_file = '/home/host/difuzz-rtl/Fuzzer/'+preprocessor.base+'/asm_debug_si/bug_{}.si'.format(i)
            if in_file: (sim_input, data, assert_intr) = mutator.read_siminput(in_file)
            else: (sim_input, data) = mutator.get(ADD_POC, ADD_CONTROL, ADD_ANTLR4, assert_intr=assert_intr)

            (isa_input, rtl_input, symbols) = preprocessor.process(sim_input, data, assert_intr, num_iter = i, in_file = True)

            if isa_input and rtl_input:
                ret = run_isa_test(isaHost, isa_input, stop, out, proc_num)
                if ret == proc_state.ERR_ISA_TIMEOUT: continue
                elif ret == proc_state.ERR_ISA_ASSERT: break

                try:
                    (ret, coverage) = yield rtlHost.run_test(rtl_input, assert_intr)
                except:
                    stop[0] = proc_state.ERR_RTL_SIM
                    break

                if assert_intr and ret == SUCCESS:
                    (intr_prv, epc) = checker.check_intr(symbols)
                    if epc != 0:
                        preprocessor.write_isa_intr(isa_input, rtl_input, epc)
                        ret = run_isa_test(isaHost, isa_input, stop, out, proc_num, True)
                        if ret == proc_state.ERR_ISA_TIMEOUT: continue
                        elif ret == proc_state.ERR_ISA_ASSERT: break
                    else: continue

                cause = '-'
                match = False
                if ret == SUCCESS:
                    match = checker.check(symbols)
                elif ret == ILL_MEM:
                    match = True
                    #debug_print('[DifuzzRTL] Memory access outside DRAM -- {}'. \
                    #            format(iNum), debug, True)
                    if record:
                        save_mismatch(out, proc_num, out + '/illegal',
                                    sim_input, data, iNum)
                    iNum += 1

                if not match or ret not in [SUCCESS, ILL_MEM]:
                    if multicore:
                        mNum = manager.read_num('mNum')
                        manager.write_num('mNum', mNum + 1)

                    if record:
                        save_mismatch(out, proc_num, out + '/mismatch',
                                    sim_input, data, mNum)

                    mNum += 1
                    if ret == TIME_OUT: cause = 'Timeout'
                    elif ret == ASSERTION_FAIL: cause = 'Assertion fail'
                    else: cause = 'Mismatch'

                    debug_print('[DifuzzRTL] Bug -- {} [{}]'. \
                                format(mNum, cause), debug, not match or (ret != SUCCESS))
                    return
                print("coverage -- {}:{}".format(i,coverage))
            else:
                stop[0] = proc_state.ERR_COMPILE
                # Compile failed
                break

        debug_print('[DifuzzRTL] Stop Fuzzing', debug)