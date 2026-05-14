# -*- coding: utf-8 -*-
"""
法律文书脱敏工具 - 核心检测引擎
支持检测：姓名、身份证号、手机号、银行卡号、地址、公司名称、日期、金额、邮箱、案号、律师执业证号
增强特性：身份证校验位验证、银行卡Luhn校验+BIN前缀识别、中文大写金额、座机号码、
         上下文姓名识别、已知实体传播（二次扫描）
"""

import re
from typing import List, Dict, Tuple

# 法律文书中常见的前缀词，公司名称匹配时需要剥离
_LEGAL_PREFIXES = ['被告', '原告', '申请人', '被申请人', '上诉人', '被上诉人', '第三人']

# 中国常见姓氏（覆盖约98%人口）
_COMMON_SURNAMES = set(
    '赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜'
    '戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐'
    '费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄'
    '和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁'
    '杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍'
    '虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚'
    '程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓'
    '牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙'
    '叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴郁胥能苍双'
    '闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀僧浦尚农'
    '温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘'
    '匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空'
    '关颛孤尉澹公轩辕令狐钟离呼延上官司马夏侯诸葛东方皇甫'
)

# 复姓列表
_COMPOUND_SURNAMES = set([
    '欧阳', '太史', '端木', '上官', '司马', '东方', '独孤', '南宫',
    '万俟', '闻人', '夏侯', '诸葛', '尉迟', '公羊', '赫连', '澹台',
    '皇甫', '宗政', '濮阳', '公冶', '太叔', '申屠', '公孙', '慕容',
    '仲孙', '钟离', '长孙', '宇文', '司徒', '鲜于', '司空', '令狐',
    '百里', '呼延',
])

# 身份证号前2位有效地区编码
_VALID_AREA_PREFIXES = {
    '11', '12', '13', '14', '15',
    '21', '22', '23',
    '31', '32', '33', '34', '35', '36', '37',
    '41', '42', '43', '44', '45', '46',
    '50', '51', '52', '53', '54',
    '61', '62', '63', '64', '65',
    '71', '81', '82',
}

# 常见银行卡BIN前缀（前6位）
_KNOWN_BANK_BINS = {
    '621', '622', '623', '624', '625', '626',  # 银联
    '620', '627', '628',
    '400', '512', '518', '520', '524', '525',  # Visa/MasterCard
    '356', '358',  # JCB
    '603', '606',
}

# 地址前应去除的前缀词
_ADDRESS_STRIP_PREFIXES = ['住所地', '住所', '住址', '地址', '位于', '坐落于', '坐落', '住']


def _validate_id_card(id_number: str) -> bool:
    """验证身份证号校验位"""
    if len(id_number) != 18:
        return False
    if id_number[:2] not in _VALID_AREA_PREFIXES:
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_codes = '10X98765432'
    try:
        total = sum(int(id_number[i]) * weights[i] for i in range(17))
        expected = check_codes[total % 11]
        return id_number[-1].upper() == expected
    except (ValueError, IndexError):
        return False


def _luhn_check(card_number: str) -> bool:
    """Luhn算法验证银行卡号"""
    try:
        digits = [int(d) for d in card_number]
    except ValueError:
        return False
    checksum = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _validate_bank_card(card_number: str) -> bool:
    """验证银行卡号：Luhn校验 OR 已知BIN前缀"""
    if _luhn_check(card_number):
        return True
    # BIN前缀检查（容忍OCR错误导致Luhn失败的情况）
    for prefix in _KNOWN_BANK_BINS:
        if card_number.startswith(prefix):
            return True
    return False


def _is_valid_name(name: str) -> bool:
    """验证是否为有效的中文姓名"""
    if len(name) < 2 or len(name) > 4:
        return False
    # 排除含有明显非姓名用字
    bad_chars = set('的了在于与和或及向往从被将把给对因为由此省市区县号路街道楼层室'
                    '元角分年月日时第条款项')
    for ch in name:
        if ch in bad_chars:
            return False
    # 检查姓氏
    if name[:2] in _COMPOUND_SURNAMES:
        return True
    if name[0] in _COMMON_SURNAMES:
        return True
    return False


def _mask_company(text: str) -> str:
    """公司名称脱敏"""
    prefix = ''
    for p in _LEGAL_PREFIXES:
        if text.startswith(p):
            prefix = p
            text = text[len(p):]
            break
    if len(text) > 3:
        masked = text[0] + '**' + text[-2:]
    else:
        masked = '***'
    return prefix + masked


def _mask_name_text(name: str) -> str:
    """对姓名文本进行脱敏"""
    if name and len(name) >= 2:
        return name[0] + '*' * (len(name) - 1)
    return '**'


def _mask_name(m) -> str:
    """姓名脱敏（从match对象中提取）"""
    name = None
    for i in range(1, len(m.groups()) + 1):
        try:
            if m.group(i):
                name = m.group(i)
                break
        except IndexError:
            break
    if not name:
        name = m.group(0)
    return _mask_name_text(name)


def _mask_phone(text: str) -> str:
    """电话号码脱敏"""
    digits = re.sub(r'[\-\s]', '', text)
    if len(digits) == 11 and digits.startswith('1'):
        return digits[:3] + '****' + digits[-4:]
    elif len(digits) >= 10:
        return digits[:3] + '****' + digits[-3:]
    else:
        return digits[:2] + '****' + digits[-2:] if len(digits) > 4 else '****'


def _validate_phone(text: str) -> bool:
    """验证电话号码有效性"""
    digits = re.sub(r'[\-\s]', '', text)
    if len(digits) == 11 and digits.startswith('1'):
        return digits[1] in '3456789'
    if len(digits) >= 10 and digits.startswith('0'):
        return True
    if 7 <= len(digits) <= 8:
        return True
    return False


def _validate_name_match(m, text: str = '') -> bool:
    """验证姓名匹配的有效性"""
    name = None
    for i in range(1, len(m.groups()) + 1):
        try:
            if m.group(i):
                name = m.group(i)
                break
        except IndexError:
            break
    if not name:
        return False
    return _is_valid_name(name)


class SensitiveDetector:
    """敏感信息检测器"""

    def __init__(self):
        self.rules = self._build_rules()

    def _build_rules(self) -> Dict[str, dict]:
        """构建检测规则"""
        return {
            "id_card": {
                "name": "身份证号",
                "pattern": re.compile(
                    r'(?<![0-9])[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9])'
                ),
                "description": "18位身份证号码（含校验位验证）",
                "mask_func": lambda m: m[0][:6] + '****' + m[0][-4:],
                "validator": lambda m, t: _validate_id_card(m.group(0))
            },
            "phone": {
                "name": "手机号/电话",
                "pattern": re.compile(
                    # 手机号
                    r'(?<![0-9\-])1[3-9]\d{9}(?![0-9])'
                    # 座机（带区号+分隔符）
                    r'|(?<![0-9])0\d{2,3}[\-\s]\d{7,8}(?![0-9\-])'
                ),
                "description": "手机号码及座机号码",
                "mask_func": lambda m: _mask_phone(m[0]),
                "validator": lambda m, t: _validate_phone(m.group(0))
            },
            "bank_card": {
                "name": "银行卡号",
                "pattern": re.compile(
                    r'(?<![0-9])[1-9]\d{15,18}(?![0-9])'
                ),
                "description": "16-19位银行卡号",
                "mask_func": lambda m: m[0][:4] + ' **** **** ' + m[0][-4:],
                "validator": lambda m, t: _validate_bank_card(m.group(0))
            },
            "email": {
                "name": "邮箱地址",
                "pattern": re.compile(
                    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
                ),
                "description": "电子邮箱地址",
                "mask_func": lambda m: m[0][0] + '***@' + m[0].split('@')[1]
            },
            "date": {
                "name": "日期",
                "pattern": re.compile(
                    r'(?:19|20)\d{2}\s*[年/\-\.]\s*(?:0?[1-9]|1[0-2])\s*[月/\-\.]\s*(?:3[01]|[12]\d|0?[1-9])\s*[日号]?'
                    r'|(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?![0-9])'
                ),
                "description": "日期信息（支持多种格式）",
                "mask_func": lambda m: '****年**月**日'
            },
            "amount": {
                "name": "金额",
                "pattern": re.compile(
                    # 带货币前缀的金额
                    r'(?:人民币|￥|¥|RMB|USD|美元)\s*[\d,]+\.?\d*\s*(?:元|万元|亿元|千元|百元)?'
                    # 纯数字+万/亿单位
                    r'|[\d,]{1,}\.?\d*\s*(?:万元|亿元)'
                    # 4位以上数字+元
                    r'|[\d,]{4,}\.?\d*\s*元'
                    # 中文大写金额
                    r'|[零壹贰叁肆伍陆柒捌玖拾佰仟万亿]+元(?:[零壹贰叁肆伍陆柒捌玖拾角分整正]+)?'
                ),
                "description": "金额信息（含中文大写金额）",
                "mask_func": lambda m: '***元'
            },
            "case_number": {
                "name": "案号",
                "pattern": re.compile(
                    # 标准案号格式，法院缩写可含数字（如"京01"）
                    r'[\(（]\s*(?:19|20)\d{2}\s*[\)）]\s*[\u4e00-\u9fa5\d]{1,8}'
                    r'\s*(?:民初|民终|民再|民申|民辖|刑初|刑终|刑再|行初|行终|行再|'
                    r'执异|执复|执监|执恢|初|终|再|执|破|监|刑|民|行|赔|协外认|认复|'
                    r'财保|知|商|仲|劳仲|经仲)'
                    r'\s*(?:字\s*)?第?\s*\d{1,10}\s*号'
                ),
                "description": "法院/仲裁案号",
                "mask_func": lambda m: '(****)***第***号'
            },
            "address": {
                "name": "地址",
                "pattern": re.compile(
                    # 以省开头的完整地址
                    r'(?:[\u4e00-\u9fa5]{2,8}(?:省|自治区))'
                    r'(?:[\u4e00-\u9fa5]{1,10}(?:市|地区|自治州|盟))?'
                    r'(?:[\u4e00-\u9fa5]{1,10}(?:区|县|旗))?'
                    r'(?:[\u4e00-\u9fa5a-zA-Z0-9]{1,30}(?:路|街|道|巷|弄|里|村|镇|乡|大道|大街|花园|小区|苑|园|庄|城|湾|府|庭|居|坊))?'
                    r'(?:[\u4e00-\u9fa5a-zA-Z0-9]{1,30}(?:号|幢|栋|楼|层|室|单元|组|座|期))*'
                    # 以"市"开头 + 路/街/小区等
                    r'|(?:[\u4e00-\u9fa5]{2,6}市)'
                    r'(?:[\u4e00-\u9fa5]{1,10}(?:区|县|旗|市))?'
                    r'(?:[\u4e00-\u9fa5a-zA-Z0-9]{1,30}(?:路|街|道|巷|弄|里|村|镇|乡|大道|大街|花园|小区|苑|园|庄|城|湾|府|庭|居|坊))'
                    r'(?:[\u4e00-\u9fa5a-zA-Z0-9]{1,30}(?:号|幢|栋|楼|层|室|单元|组|座|期))*'
                    # 以"区/县"开头 + 路/街
                    r'|(?:[\u4e00-\u9fa5]{2,8}(?:区|县))'
                    r'(?:[\u4e00-\u9fa5a-zA-Z0-9]{2,30}(?:路|街|道|巷|弄|里|村|镇|乡|大道|大街|花园|小区|苑|园|庄|城|湾|府|庭|居|坊))'
                    r'(?:[\u4e00-\u9fa5a-zA-Z0-9]{1,30}(?:号|幢|栋|楼|层|室|单元|组|座|期))*'
                ),
                "description": "详细地址信息",
                "mask_func": lambda m: m[0][:3] + '****' if len(m[0]) > 4 else '****'
            },
            "company": {
                "name": "公司/机构名称",
                "pattern": re.compile(
                    # 标准公司名称：至少4个汉字 + 后缀
                    r'[\u4e00-\u9fa5][\u4e00-\u9fa5（()）]{3,28}(?:有限公司|股份有限公司|有限责任公司|集团有限公司|集团公司|合伙企业|事务所|研究院|研究所|基金会|协会|学会|中心)'
                    # 银行/保险/证券：至少3字+后缀
                    r'|[\u4e00-\u9fa5]{3,20}(?:银行|保险公司|证券公司|信托公司|基金公司)'
                    # 法院、检察院等国家机关
                    r'|[\u4e00-\u9fa5]{2,10}(?:人民法院|人民检察院|检察院|公安局|司法局|仲裁委员会|仲裁委|仲裁院|公证处|法律援助中心)'
                ),
                "description": "公司、机构、法院等名称",
                "mask_func": lambda m: _mask_company(m[0])
            },
            "name": {
                "name": "姓名",
                "pattern": re.compile(
                    # 法律角色前缀 + 分隔符(至少一个) + 姓名
                    r'(?:原告|被告|申请人|被申请人|上诉人|被上诉人|第三人|再审申请人|被申请执行人|'
                    r'委托代理人|委托诉讼代理人|法定代表人|法定代理人|证人|鉴定人|当事人|'
                    r'甲方|乙方|丙方|丁方|担保人|保证人|借款人|出借人|贷款人|'
                    r'出租人|承租人|买受人|出卖人|转让人|受让人|'
                    r'代理人|辩护人|指定辩护人|'
                    r'附带民事诉讼原告人|附带民事诉讼被告人|'
                    r'被执行人|执行人|抗诉机关|自诉人|'
                    r'权利人|义务人|债权人|债务人|'
                    r'被告人|犯罪嫌疑人|罪犯|被害人|受害人)[：:\s，,]+([\u4e00-\u9fa5]{2,4})'
                    # 审判人员
                    r'|(?:审判员|书记员|审判长|陪审员|执行员|人民陪审员|'
                    r'代理审判员|助理审判员|执行法官|承办法官|独任审判员)[：:\s]+([\u4e00-\u9fa5]{2,4})'
                    # 签名/具状人等
                    r'|(?:签名|签字|具状人|起诉人|声明人|申报人)[：:\s]+([\u4e00-\u9fa5]{2,4})'
                ),
                "description": "当事人姓名",
                "mask_func": lambda m: _mask_name(m),
                "validator": lambda m, t: _validate_name_match(m, t)
            },
            "lawyer_id": {
                "name": "律师执业证号",
                "pattern": re.compile(
                    r'(?<![0-9])[12]\d{16}(?![0-9])'
                ),
                "description": "17位律师执业证号",
                "mask_func": lambda m: m[0][:4] + '****' + m[0][-4:]
            },
        }

    def detect(self, text: str, categories: List[str] = None) -> List[Dict]:
        """
        检测文本中的敏感信息（含已知实体传播）

        Args:
            text: 待检测文本
            categories: 指定检测的类别列表，None表示全部检测

        Returns:
            检测结果列表
        """
        results = []
        rules_to_use = self.rules if categories is None else {
            k: v for k, v in self.rules.items() if k in categories
        }

        detected_ranges = []

        # 按优先级排序检测
        priority_order = [
            'id_card', 'case_number', 'phone', 'lawyer_id',
            'bank_card', 'email', 'date', 'amount',
            'address', 'company', 'name'
        ]

        for category in priority_order:
            if category not in rules_to_use:
                continue
            rule = rules_to_use[category]
            pattern = rule['pattern']
            validator = rule.get('validator')

            for match in pattern.finditer(text):
                start, end = match.start(), match.end()

                # 运行验证器
                if validator and not validator(match, text):
                    continue

                # 检查重叠
                is_overlap = False
                for (ds, de) in detected_ranges:
                    if not (end <= ds or start >= de):
                        is_overlap = True
                        break
                if is_overlap:
                    continue

                # 姓名类别：提取实际姓名部分
                if category == 'name':
                    actual_name = None
                    for i in range(1, len(match.groups()) + 1):
                        try:
                            if match.group(i):
                                actual_name = match.group(i)
                                break
                        except IndexError:
                            break
                    if actual_name:
                        name_start = text.find(actual_name, start)
                        if name_start >= 0:
                            start = name_start
                            end = name_start + len(actual_name)
                    else:
                        continue

                # 地址：剥离"住"/"住所地"等前缀
                if category == 'address':
                    start, end = self._strip_address_prefix(text, start, end)

                # 公司名称验证
                if category == 'company':
                    matched = text[start:end]
                    if not self._validate_company(matched):
                        continue

                matched_text = text[start:end]
                detected_ranges.append((start, end))

                # 地址类使用剥离后的文本生成掩码
                if category == 'address':
                    masked = matched_text[:3] + '****' if len(matched_text) > 4 else '****'
                else:
                    masked = self._apply_mask(match, rule, category)

                results.append({
                    'category': category,
                    'category_name': rule['name'],
                    'text': matched_text,
                    'start': start,
                    'end': end,
                    'masked': masked
                })

        # ===== 第二轮：已知实体传播 =====
        # 将第一轮检测到的姓名和公司名在全文中查找其他出现位置
        known_names = set()
        known_companies = set()
        for r in results:
            if r['category'] == 'name':
                known_names.add(r['text'])
            elif r['category'] == 'company':
                # 剥离法律前缀后记录
                clean = r['text']
                for p in _LEGAL_PREFIXES:
                    if clean.startswith(p):
                        clean = clean[len(p):]
                        break
                if len(clean) >= 4:
                    known_companies.add(clean)

        # 扫描已知姓名的其他出现位置
        if 'name' in rules_to_use or categories is None:
            for name in known_names:
                for match in re.finditer(re.escape(name), text):
                    start, end = match.start(), match.end()
                    is_overlap = False
                    for (ds, de) in detected_ranges:
                        if not (end <= ds or start >= de):
                            is_overlap = True
                            break
                    if is_overlap:
                        continue
                    detected_ranges.append((start, end))
                    results.append({
                        'category': 'name',
                        'category_name': '姓名',
                        'text': name,
                        'start': start,
                        'end': end,
                        'masked': _mask_name_text(name)
                    })

        # 扫描已知公司名的其他出现位置
        if 'company' in rules_to_use or categories is None:
            for company in known_companies:
                for match in re.finditer(re.escape(company), text):
                    start, end = match.start(), match.end()
                    is_overlap = False
                    for (ds, de) in detected_ranges:
                        if not (end <= ds or start >= de):
                            is_overlap = True
                            break
                    if is_overlap:
                        continue
                    detected_ranges.append((start, end))
                    results.append({
                        'category': 'company',
                        'category_name': '公司/机构名称',
                        'text': company,
                        'start': start,
                        'end': end,
                        'masked': _mask_company(company)
                    })

        # 按位置排序
        results.sort(key=lambda x: x['start'])
        return results

    def _strip_address_prefix(self, text: str, start: int, end: int) -> Tuple[int, int]:
        """从地址匹配中剥离前面的'住'/'住所地'等非地址词"""
        matched = text[start:end]
        for prefix in _ADDRESS_STRIP_PREFIXES:
            if matched.startswith(prefix):
                start += len(prefix)
                break
        return start, end

    def _validate_company(self, text: str) -> bool:
        """验证公司名称匹配是否有效"""
        clean = text
        for p in _LEGAL_PREFIXES:
            if clean.startswith(p):
                clean = clean[len(p):]
                break
        # 公司名至少4个字
        if len(clean) < 4:
            return False
        # 排除明显误匹配
        if re.search(r'[与诉及](?:被告|原告|申请人)', clean):
            return False
        return True

    def _apply_mask(self, match, rule, category):
        """应用脱敏掩码"""
        try:
            return rule['mask_func'](match)
        except Exception:
            text = match.group(0)
            if len(text) > 4:
                return text[:2] + '*' * (len(text) - 4) + text[-2:]
            return '*' * len(text)

    def desensitize(self, text: str, categories: List[str] = None,
                    selected_items: List[int] = None) -> Tuple[str, List[Dict]]:
        """
        对文本进行脱敏处理

        Args:
            text: 待脱敏文本
            categories: 指定脱敏的类别列表
            selected_items: 指定脱敏的条目索引列表，None表示全部脱敏

        Returns:
            (脱敏后文本, 检测结果列表)
        """
        results = self.detect(text, categories)

        if selected_items is not None:
            results_to_apply = [results[i] for i in selected_items if i < len(results)]
        else:
            results_to_apply = results

        # 从后向前替换，避免位置偏移
        desensitized_text = text
        for item in sorted(results_to_apply, key=lambda x: x['start'], reverse=True):
            desensitized_text = (
                desensitized_text[:item['start']] +
                item['masked'] +
                desensitized_text[item['end']:]
            )

        return desensitized_text, results

    def get_categories(self) -> List[Dict]:
        """获取所有支持的脱敏类别"""
        return [
            {
                'id': key,
                'name': rule['name'],
                'description': rule['description']
            }
            for key, rule in self.rules.items()
        ]
