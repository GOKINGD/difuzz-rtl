import os
import random

from riscv_definitions import *
from word import *
from src.utils import *

""" rvInstGenerator
Generates syntactically, semantically desirable unit of instructions

Properties
 2. Compilable
 1. Guarantee forward progress and end (No loop)
"""
class rvInstGenerator():
    def __init__(self, isa='RV64G'):
        isas = ['trap_ret']

        if 'I' in isa:
            isas += [ 'rv32i' ]
        if 'M' in isa:
            isas += [ 'rv32m' ]
        if 'A' in isa:
            isas += [ 'rv32a' ]
        if 'F' in isa:
            isas += [ 'rv32f' ]
        if 'zifencei' in isa:
            isas += [ 'rv_zifencei' ]
        if 'zicsr' in isa:
            isas += [ 'rv_zicsr' ]
        if 'D' in isa:
            isas += [ 'rv32d' ]
        if 'Q' in isa:
            isas += [ 'rv32q' ]
        if 'G' in isa:
            isas += [ 'rv32i', 'rv32a', 'rv32f', 'rv_zifencei', 'rv_zicsr' ]

        if 'RV64' in isa:
            isas = self.extend(isas)
        self.rv_isas = isas

        self.opcodes_map = {}
        for isa in self.rv_isas:
            self.opcodes_map.update(rv_opcodes[isa])

        self.opcodes = list(self.opcodes_map.keys())

        self.prefix_num = 0
        self.main_num = 0
        self.suffix_num = 0

        self.xNums = [ i for i in range(32) ]
        self.fNums = [ i for i in range(32) ]

        self.used_xNums = set([])
        self.used_fNums = set([])
        self.used_imms = set([])


    def extend(self, isas):
        extended_isas = []
        for isa in isas:
            extended_isas.append(isa)
            if '32' in isa:
                extended_isas.append(isa.replace('32', '64'))

        return extended_isas

    def reset(self):
        self.prefix_num = 0
        self.main_num = 0
        self.suffix_num = 0

        self.used_xNums = set([])
        self.used_fNums = set([])
        self.used_imms = set([])

    def _get_xregs(self, region=(0, 31), no_zero=False, thres=0.2):
        if region == (0, 31) and len(self.used_xNums) > 0 and random.random() < thres:
            xNum = random.choice(list(self.used_xNums))
        else:
            xNum = random.choice(self.xNums[region[0]:region[1]])
            used_xNums = list(self.used_xNums) + [ xNum ]
            self.used_xNums = set(used_xNums)

        if no_zero and xNum == 0:
            xNum = random.choice(list(self.xNums)[1:])

        return 'x' + str(xNum)

    def _get_fregs(self, thres=0.2):
        if len(self.used_fNums) > 0 and random.random() < thres:
            fNum = random.choice(list(self.used_fNums))
        else:
            fNum = random.choice(self.fNums)
            used_fNums = list(self.used_fNums) + [ fNum ]
            self.used_fNums = set(used_fNums)
        return 'f' + str(fNum)

    def _get_imm(self, iName, align, thres=0.2, zfthres=0.2, alignthres=1):
        assert align & (align - 1) == 0, 'align must be power of 2'
        if 'uimm' in iName:
            sign = ''
            width = int(iName[4:])
        else:
            sign = random.choice(['', '-'])
            width = int(iName[3:]) - 1

        mask = (1 << width) - 1

        rand = random.random()
        if rand < alignthres:
            align_mask = ~(align - 1)
        else:
            align_mask = 0

        mask = mask & align_mask

        rand = random.random()
        if len(self.used_imms) > 0 and rand < thres:
            imm = random.choice(list(self.used_imms))
            return sign + str(mask & imm)
        elif rand < thres + zfthres:
            imm = random.choice([ 0x0, 0xffffffff ])
            return sign + str(mask & imm)
        else:
            imm = random.randint(0, mask)
            used_imms = list(self.used_imms) + [ imm ]
            self.used_imms = set(used_imms)
            return sign + str(mask & imm)

    def _get_symbol(self, tpe, my_label, max_label, part):
        if tpe == MEM_W:
            n = random.randint(0, 5) # TODO, num_mem_sections = 6
            k = random.randint(0, 27)
            symbol = 'd_' + str(n) + '_' + str(k)
        elif tpe == MEM_R:
            rand = random.random()
            if rand < 0.2:
                n = random.randint(0, max_label)
                symbol = part + str(n)
            else:
                n = random.randint(0, 5)
                k = random.randint(0, 27)
                symbol = 'd_' + str(n) + '_' + str(k)
        else:
            if tpe in [ CF_J, CF_RET ]:
                num = random.randint(my_label + 1, max_label)
                symbol = part + str(num)
            else:
                num = random.randint(my_label + 1, max_label)
                symbol = part + str(num)

        return symbol

    """ Word
    Set of instructions which forms compilable, forward-guaranteeing sequence.
    """
    def get_word(self, part):
        if part == PREFIX:
            opcode = random.choice(list(rv_zicsr.keys()))
            label_num = self.prefix_num
            self.prefix_num += 1
        elif part == MAIN:
            opcode = random.choice(self.opcodes)
            label_num = self.main_num
            self.main_num += 1
        else: # SUFFIX
            opcode = random.choice(self.opcodes)
            label_num = self.suffix_num
            self.suffix_num += 1

        (syntax, xregs, fregs, imms, symbols) = self.opcodes_map.get(opcode)
        xregs = list(xregs)
        fregs = list(fregs)
        imms = list(imms)
        symbols = list(symbols)

        tpe = NONE
        insts = [ syntax ]
        for (key, tup) in opcodes_words.items():
            key_opcodes = tup[0]
            key_word = tup[1]
            if opcode in key_opcodes:
                (tpe, insts) = key_word(opcode, syntax, xregs, fregs, imms, symbols)
                break
        tpe_list = [tpe] * len(insts)
        xregs_list = []
        fregs_list = []
        imms_list = []
        symbols_list = []
        for i in range(len(insts)):
            xregs_list.append(xregs)
            fregs_list.append(fregs)
            imms_list.append(imms)
            symbols_list.append(symbols)
        if part == MAIN:
            cnt = 10 - len(insts)
            while cnt > 0:
                flag = 0
                opcode = random.choice(self.opcodes)
                (xsyntax, xxregs, xfregs, ximms, xsymbols) = self.opcodes_map.get(opcode)
                xxregs_list = list(xxregs)
                xfregs_list = list(xfregs)
                ximms_list = list(ximms)
                xsymbols_list = list(xsymbols)
                for (key, tup) in opcodes_words.items():
                    key_opcodes = tup[0]
                    key_word = tup[1]
                    if opcode in key_opcodes:
                        (tpe, xinst) = key_word(opcode, xsyntax, xxregs_list, xfregs_list, ximms_list, xsymbols_list)
                        insts += xinst
                        tpe_list += [tpe] * len(xinst)
                        for i in range(len(xinst)):
                            xregs_list.append(xxregs_list)
                            fregs_list.append(xfregs_list)
                            imms_list.append(ximms_list)
                            symbols_list.append(xsymbols_list)
                        flag = 1
                        cnt -= (len(xinst)-1)
                        break
                if flag == 0:
                    insts.append(xsyntax)
                    xregs_list.append(xxregs_list)
                    fregs_list.append(xfregs_list)
                    imms_list.append(ximms_list)
                    symbols_list.append(xsymbols_list)
                    tpe_list += [NONE]
                cnt -= 1
            # print(len(tpe_list))
            # print("****{}".format(len(insts)))
            # print("&&&&{}".format(len(xregs_list)))
            # print("((((())))){}".format(len(insts)))
            # print(len(xregs_list))
            # print(len(fregs_list))
            # print(len(imms_list))
            # print(len(symbols_list))
        word = Word(label_num, insts, tpe, xregs_list, fregs_list, imms_list, symbols_list, tpe_list)
        return word

    def populate_word(self, word: Word, max_label: int, part: str):
        if word.populated:
            return
        region = (0, 31)
        if part == PREFIX:
            region = (10, 15)

        if part == MAIN:
            opvals = [{} for i in range(len(word.tpe_list))]
            for i in range(len(word.tpe_list)):
                for xreg in word.xregs_list[i]:
                    if word.tpe_list[i] == NONE:
                        opvals[i][xreg] = self._get_xregs()
                    else:
                        opvals[i][xreg] = self._get_xregs(region, True)
                for freg in word.fregs_list[i]:
                    opvals[i][freg] = self._get_fregs()
                for (imm, align) in word.imms_list[i]:
                    opvals[i][imm] = self._get_imm(imm, align)
                for symbol in word.symbols_list[i]:
                    opvals[i][symbol] = self._get_symbol(word.tpe_list[i], word.label, max_label, part)            
        else:
            opvals = {}
            for i in range(len(word.tpe_list)):
                for xreg in word.xregs_list[0]:
                    if word.tpe_list[0] == NONE:
                        opvals[xreg] = self._get_xregs()
                    else:
                        opvals[xreg] = self._get_xregs(region, True)

                for freg in word.fregs_list[0]:
                    opvals[freg] = self._get_fregs()

                for (imm, align) in word.imms_list[0]:
                    opvals[imm] = self._get_imm(imm, align)

                for symbol in word.symbols_list[0]:
                    opvals[symbol] = self._get_symbol(word.tpe, word.label, max_label, part)
        word.populate(opvals, part)
